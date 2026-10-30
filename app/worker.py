"""Stream ingest and transcription.

Each enabled stream gets two asyncio tasks:
  * reader      — runs ffmpeg against the HLS URL, decodes to 16 kHz mono PCM and
                  cuts it into fixed-length chunks.
  * transcriber — sends each chunk (as WAV) to whisper-asr-webservice and stores the text.

A bounded queue sits between them so a slow Whisper never stalls the network read.
"""
import array
import asyncio
import io
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave

SAMPLE_RATE = 16000
BYTES_PER_SEC = SAMPLE_RATE * 2  # s16le mono

# Whisper's favourite phantom lines on music / silence.
HALLUCINATIONS = {
    "", "you", "thank you", "thanks for watching", "thank you for watching",
    "thanks for watching!", "please subscribe", "bye", "so", "uh", "um",
    "subtitles by the amaraorg community", "music", "applause", "silence",
}


def _normalise(text):
    return re.sub(r"[^a-z ]", "", text.lower()).strip()


def is_hallucination(text):
    t = _normalise(text)
    if t in HALLUCINATIONS:
        return True
    # bracketed sound cues only, e.g. "[Music]" or "(upbeat music)"
    if re.fullmatch(r"\s*([\[\(][^\]\)]*[\]\)]\s*)+", text):
        return True
    # one short word repeated over and over
    words = t.split()
    return len(words) >= 6 and len(set(words)) == 1


def pcm_rms(pcm: bytes) -> float:
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    if not samples:
        return 0.0
    step = 4  # sampling every 4th value is plenty for a loudness gate
    sub = samples[::step]
    return math.sqrt(sum(s * s for s in sub) / len(sub))


def pcm_to_wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return buf.getvalue()


def whisper_request(base_url, wav: bytes, language="", prompt="", vad=True, timeout=180):
    """Blocking POST to whisper-asr-webservice /asr. Returns the transcript text."""
    params = {"task": "transcribe", "output": "json", "encode": "true"}
    if language:
        params["language"] = language
    if vad:
        params["vad_filter"] = "true"
    if prompt:
        params["initial_prompt"] = prompt[-200:]
    url = base_url.rstrip("/") + "/asr?" + urllib.parse.urlencode(params)

    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="audio_file"; filename="chunk.wav"\r\n'
        "Content-Type: audio/wav\r\n\r\n"
    ).encode() + wav + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            text = data.get("text")
            if text is None and data.get("segments"):
                text = " ".join(s.get("text", "") for s in data["segments"])
            return (text or "").strip()
    except json.JSONDecodeError:
        pass
    return raw.strip()


class Broker:
    """Fan-out of live events to every open browser (Server-Sent Events)."""

    def __init__(self):
        self.subscribers = set()

    def subscribe(self):
        q = asyncio.Queue(maxsize=500)
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q):
        self.subscribers.discard(q)

    def publish(self, event):
        for q in list(self.subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # a stalled browser just misses events; it reloads on reconnect


class StreamWorker:
    def __init__(self, manager, stream):
        self.m = manager
        self.id = stream["id"]
        self.url = stream["url"]
        self.language = stream["language"]
        self.status = "stopped"
        self.error = ""
        self.chunks = 0
        self.last_text_at = None
        self.queue = asyncio.Queue(maxsize=12)
        self.proc = None
        self.tasks = []
        self.stopping = False
        self.last_text = ""

    # lifecycle -------------------------------------------------------------
    def start(self):
        self.stopping = False
        self.status = "connecting"
        self.tasks = [asyncio.create_task(self._reader()), asyncio.create_task(self._transcriber())]

    async def stop(self):
        self.stopping = True
        self._kill()
        for t in self.tasks:
            t.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks = []
        self._set("stopped", "")

    def _kill(self):
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.kill()
            except ProcessLookupError:
                pass

    def _set(self, status, error=None):
        self.status = status
        if error is not None:
            self.error = error
        self.m.broker.publish({"type": "status", **self.info()})

    def info(self):
        return {"stream_id": self.id, "status": self.status, "error": self.error,
                "chunks": self.chunks, "backlog": self.queue.qsize(),
                "last_text_at": self.last_text_at}

    # reader ----------------------------------------------------------------
    def _ffmpeg_cmd(self):
        return [
            "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
            # network only — never let a stream URL read local files
            "-protocol_whitelist", "http,https,tcp,tls,crypto,hls,httpproxy",
            "-user_agent", "Mozilla/5.0 (StreamTranscriber)",
            "-reconnect", "1", "-reconnect_streamed", "1",
            "-reconnect_on_network_error", "1", "-reconnect_delay_max", "10",
            "-rw_timeout", "20000000",
            "-i", self.url,
            "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "pipe:1",
        ]

    async def _reader(self):
        backoff = 5
        first_attempt = True
        while not self.stopping:
            if first_attempt:
                self._set("connecting", "")
            # on retries keep showing the last error until audio actually flows again
            first_attempt = False
            stderr_tail = []
            got_audio = False
            try:
                self.proc = await asyncio.create_subprocess_exec(
                    *self._ffmpeg_cmd(), stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE)
                err_task = asyncio.create_task(self._drain_stderr(stderr_tail))
                chunk_secs = self.m.db.setting("chunk_seconds", int)
                chunk_secs = min(max(chunk_secs, 5), 60)
                size = chunk_secs * BYTES_PER_SEC
                buf = bytearray()
                while not self.stopping:
                    try:
                        data = await asyncio.wait_for(self.proc.stdout.read(65536), timeout=45)
                    except asyncio.TimeoutError:
                        stderr_tail.append("No audio received for 45 seconds (stream stalled)")
                        break
                    if not data:  # ffmpeg exited
                        if len(buf) >= BYTES_PER_SEC * 2:
                            await self._enqueue(bytes(buf))
                        break
                    if not got_audio:
                        got_audio = True
                        backoff = 5
                        self._set("live", "")
                        self.m.db.log("info", "Receiving audio", self.id)
                    buf += data
                    while len(buf) >= size:
                        await self._enqueue(bytes(buf[:size]))
                        del buf[:size]
                self._kill()
                await self.proc.wait()
                err_task.cancel()
            except asyncio.CancelledError:
                self._kill()
                raise
            except FileNotFoundError:
                self._set("error", "ffmpeg is not installed in the container")
                return
            except Exception as e:  # keep the loop alive whatever happens
                stderr_tail.append(str(e))

            if self.stopping:
                return
            reason = (stderr_tail[-1] if stderr_tail else "Stream ended").strip()
            self.m.db.log("warning", f"ffmpeg stopped: {reason}. Retrying in {backoff}s", self.id)
            self._set("error" if not got_audio else "reconnecting", reason)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 120)

    async def _drain_stderr(self, tail):
        async for line in self.proc.stderr:
            s = line.decode(errors="replace").strip()
            if s:
                tail.append(s)
                del tail[:-5]

    async def _enqueue(self, pcm):
        ended = time.time()
        if self.queue.full():
            self.queue.get_nowait()
            self.m.db.log("warning", "Whisper is falling behind; dropped an audio chunk", self.id)
        await self.queue.put((ended - len(pcm) / BYTES_PER_SEC, pcm))

    # transcriber -----------------------------------------------------------
    async def _transcriber(self):
        while True:
            started, pcm = await self.queue.get()
            self.chunks += 1
            db = self.m.db
            if pcm_rms(pcm) < db.setting("silence_threshold", float):
                self.m.broker.publish({"type": "status", **self.info()})
                continue
            language = self.language or db.setting("default_language")
            prompt = self.last_text if db.setting("use_prompt", int) else ""
            try:
                async with self.m.whisper_slot():
                    text = await asyncio.to_thread(
                        whisper_request, db.setting("whisper_url"), pcm_to_wav(pcm),
                        language, prompt, bool(db.setting("vad_filter", int)))
                if self.error.startswith("Whisper"):
                    self._set(self.status, "")  # Whisper is back — clear the warning
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                msg = f"Whisper request failed: {getattr(e, 'reason', e)}"
                db.log("error", msg, self.id)
                self._set(self.status, msg)
                continue
            text = re.sub(r"\s+", " ", text).strip()
            if not text or is_hallucination(text):
                continue
            # Whisper sometimes echoes the prompt back verbatim — skip exact repeats.
            if text == self.last_text:
                continue
            self.last_text = text
            self.last_text_at = time.time()
            duration = len(pcm) / BYTES_PER_SEC
            seg_id = db.x("INSERT INTO segments(stream_id, ts, duration, text) VALUES (?, ?, ?, ?)",
                          (self.id, started, duration, text))
            self.m.broker.publish({"type": "segment", "stream_id": self.id, "id": seg_id,
                                   "ts": started, "duration": duration, "text": text})
            self.m.broker.publish({"type": "status", **self.info()})


class Manager:
    def __init__(self, db):
        self.db = db
        self.broker = Broker()
        self.workers = {}
        self._sem = None
        self._sem_size = 0

    def whisper_slot(self):
        size = min(max(self.db.setting("max_concurrent", int), 1), 8)
        if self._sem is None or size != self._sem_size:
            self._sem, self._sem_size = asyncio.Semaphore(size), size
        return self._sem

    async def start_all(self):
        for s in self.db.q("SELECT * FROM streams WHERE enabled=1"):
            await self.start(s["id"])
        asyncio.create_task(self._housekeeping())

    async def start(self, stream_id):
        await self.stop(stream_id)
        s = self.db.one("SELECT * FROM streams WHERE id=?", (stream_id,))
        if not s:
            return
        w = StreamWorker(self, s)
        self.workers[stream_id] = w
        w.start()

    async def stop(self, stream_id):
        w = self.workers.pop(stream_id, None)
        if w:
            await w.stop()
            self.broker.publish({"type": "status", **w.info()})

    async def stop_all(self):
        for sid in list(self.workers):
            await self.stop(sid)

    def info(self, stream_id):
        w = self.workers.get(stream_id)
        if w:
            return w.info()
        return {"stream_id": stream_id, "status": "stopped", "error": "", "chunks": 0,
                "backlog": 0, "last_text_at": None}

    async def _housekeeping(self):
        while True:
            try:
                self.db.prune(self.db.setting("retention_days", int))
            except Exception as e:
                print("prune failed:", e, flush=True)
            await asyncio.sleep(3600)
