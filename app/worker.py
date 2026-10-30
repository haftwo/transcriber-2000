"""Stream ingest and transcription.

Each enabled stream gets two asyncio tasks:
  * reader      — runs ffmpeg against the HLS URL, decodes to 16 kHz mono PCM and
                  cuts it into fixed-length chunks. The same ffmpeg also writes an MP3
                  recording in fixed-length files, so every line can be played back.
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
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave

from .db import rec_dir

SAMPLE_RATE = 16000
REC_SEG_SECONDS = 60  # length of each recorded MP3 file
THUMB_SECONDS = 5     # one video thumbnail every this many seconds (streams with video only)
THUMB_HEIGHT = 144    # pixels; width follows the video's shape
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
        self.rec = None        # current recording row (dict) while audio flows
        self.rec_bytes = 0     # PCM bytes received in the current recording
        self.has_video = None  # does the stream carry video? (probed once per worker)

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
    NET_OPTS = [
        # network only — never let a stream URL read local files
        "-protocol_whitelist", "http,https,tcp,tls,crypto,hls,httpproxy",
        "-user_agent", "Mozilla/5.0 (Transcriber2000)",
    ]

    async def _probe_video(self):
        """True if the stream has a video track. Asked once per worker; a failed probe counts as no video."""
        if self.has_video is not None:
            return self.has_video
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "error", *self.NET_OPTS, "-rw_timeout", "15000000",
                "-select_streams", "v", "-show_entries", "stream=codec_type", "-of", "csv=p=0", self.url,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=25)
            self.has_video = b"video" in out
        except (asyncio.TimeoutError, OSError):
            if proc and proc.returncode is None:
                proc.kill()
            return False  # try again on the next take
        if self.has_video and self.m.db.setting("video_thumbs", int):
            self.m.db.log("info", "Stream has video: saving timeline thumbnails", self.id)
        # file a new stream under Video or Audio in the sidebar (only if nobody has chosen yet)
        row = self.m.db.one("SELECT category FROM streams WHERE id=?", (self.id,))
        if row and not row["category"]:
            cat = "video" if self.has_video else "audio"
            self.m.db.x("UPDATE streams SET category=? WHERE id=? AND category=''", (cat, self.id))
            self.m.broker.publish({"type": "category", "stream_id": self.id, "category": cat})
        return self.has_video

    def _ffmpeg_cmd(self, rec_folder=None, thumbs=False):
        # asetpts=N/SR/TB numbers the audio by sample count, so a gap in the source
        # can't push the recording and the transcript out of step with each other.
        cmd = [
            "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", *self.NET_OPTS,
            "-reconnect", "1", "-reconnect_streamed", "1",
            "-reconnect_on_network_error", "1", "-reconnect_delay_max", "10",
            "-rw_timeout", "20000000",
        ]
        if thumbs:
            cmd += ["-skip_frame:v", "nokey"]  # decode keyframes only: thumbnails cost almost no CPU
        cmd += [
            "-i", self.url,
            "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-af", "asetpts=N/SR/TB",
            "-f", "s16le", "pipe:1",
        ]
        if rec_folder:
            kbps = min(max(self.m.db.setting("audio_bitrate", int), 32), 320)
            cmd += [
                "-vn", "-af", "asetpts=N/SR/TB", "-c:a", "libmp3lame", "-b:a", f"{kbps}k",
                "-ar", "44100", "-f", "segment", "-segment_time", str(REC_SEG_SECONDS),
                "-segment_format", "mp3",
                "-segment_format_options", "id3v2_version=0:write_xing=0",
                "-reset_timestamps", "1", os.path.join(rec_folder, "%06d.mp3"),
            ]
        if rec_folder and thumbs:
            # thumbs/000000.jpg is the first frame, 000001.jpg is THUMB_SECONDS later, and so on.
            # round=up makes each one the last keyframe at or before its moment (round=near would
            # take a frame up to half an interval late).
            cmd += [
                "-map", "0:v:0", "-an", "-sn",
                "-vf", f"setpts=PTS-STARTPTS,fps=1/{THUMB_SECONDS}:round=up,scale=-2:{THUMB_HEIGHT}",
                "-q:v", "7", "-start_number", "0", "-f", "image2",
                os.path.join(rec_folder, "thumbs", "%06d.jpg"),
            ]
        return cmd

    # recording -------------------------------------------------------------
    def _rec_begin(self, thumbs=False):
        """Create the row and folder for a new take (before ffmpeg starts)."""
        if not self.m.db.setting("record_audio", int):
            return None
        rid = self.m.db.x("INSERT INTO recordings(stream_id, started, length, seg_seconds, thumb_seconds) "
                          "VALUES (?, ?, 0, ?, ?)",
                          (self.id, time.time(), REC_SEG_SECONDS, THUMB_SECONDS if thumbs else 0))
        self.rec = self.m.db.one("SELECT * FROM recordings WHERE id=?", (rid,))
        self.rec_bytes = 0
        folder = rec_dir(self.rec)
        os.makedirs(os.path.join(folder, "thumbs") if thumbs else folder, exist_ok=True)
        return folder

    def _rec_end(self, got_audio):
        if not self.rec:
            return
        if got_audio:
            self.m.db.x("UPDATE recordings SET length=? WHERE id=?",
                        (self.rec_bytes / BYTES_PER_SEC, self.rec["id"]))
        else:  # never connected — nothing worth keeping
            self.m.db.x("DELETE FROM recordings WHERE id=?", (self.rec["id"],))
            shutil.rmtree(rec_dir(self.rec), ignore_errors=True)
        self.rec = None

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
            take_start = time.time()   # wall-clock time of the first sample in this take
            pos = 0                     # PCM bytes received in this take
            try:
                has_video = await self._probe_video()
                thumbs = has_video and self.m.db.setting("record_audio", int) and self.m.db.setting("video_thumbs", int)
                folder = self._rec_begin(bool(thumbs))
                self.proc = await asyncio.create_subprocess_exec(
                    *self._ffmpeg_cmd(folder, bool(folder and thumbs)), stdout=asyncio.subprocess.PIPE,
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
                            await self._enqueue(bytes(buf), take_start, pos - len(buf))
                        break
                    if not got_audio:
                        got_audio = True
                        backoff = 5
                        take_start = time.time()
                        if self.rec:
                            self.m.db.x("UPDATE recordings SET started=? WHERE id=?", (take_start, self.rec["id"]))
                            self.rec["started"] = take_start
                        self._set("live", "")
                        self.m.db.log("info", "Receiving audio" + (" (recording)" if self.rec else ""), self.id)
                    buf += data
                    pos += len(data)
                    self.rec_bytes = pos
                    while len(buf) >= size:
                        await self._enqueue(bytes(buf[:size]), take_start, pos - len(buf))
                        del buf[:size]
                self._kill()
                await self.proc.wait()
                err_task.cancel()
                self._rec_end(got_audio)
            except asyncio.CancelledError:
                self._kill()
                self._rec_end(got_audio)
                raise
            except FileNotFoundError:
                self._rec_end(False)
                self._set("error", "ffmpeg is not installed in the container")
                return
            except Exception as e:  # keep the loop alive whatever happens
                stderr_tail.append(str(e))
                self._rec_end(got_audio)

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

    async def _enqueue(self, pcm, take_start, byte_pos):
        offset = byte_pos / BYTES_PER_SEC   # seconds into this take
        rec_id = None
        if self.rec:
            rec_id = self.rec["id"]
            self.m.db.x("UPDATE recordings SET length=? WHERE id=?", (self.rec_bytes / BYTES_PER_SEC, rec_id))
        if self.queue.full():
            self.queue.get_nowait()
            self.m.db.log("warning", "Whisper is falling behind; dropped an audio chunk", self.id)
        await self.queue.put((take_start + offset, rec_id, offset, pcm))

    # transcriber -----------------------------------------------------------
    async def _transcriber(self):
        while True:
            started, rec_id, rec_offset, pcm = await self.queue.get()
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
            seg_id = db.x("INSERT INTO segments(stream_id, ts, duration, text, rec_id, rec_offset) "
                          "VALUES (?, ?, ?, ?, ?, ?)",
                          (self.id, started, duration, text, rec_id, rec_offset))
            self.m.broker.publish({"type": "segment", "stream_id": self.id, "id": seg_id,
                                   "ts": started, "duration": duration, "text": text,
                                   "rec_id": rec_id, "rec_offset": rec_offset})
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

    def live_length(self, rec_id):
        """Seconds recorded so far for a take that is still running, else None."""
        for w in self.workers.values():
            if w.rec and w.rec["id"] == rec_id:
                return w.rec_bytes / BYTES_PER_SEC
        return None

    def info(self, stream_id):
        w = self.workers.get(stream_id)
        if w:
            return w.info()
        return {"stream_id": stream_id, "status": "stopped", "error": "", "chunks": 0,
                "backlog": 0, "last_text_at": None}

    async def _housekeeping(self):
        while True:
            try:
                active = [w.rec["id"] for w in self.workers.values() if w.rec]
                await asyncio.to_thread(self.db.prune, self.db.setting("retention_days", int),
                                        self.db.setting("audio_retention_days", int), active)
            except Exception as e:
                print("prune failed:", e, flush=True)
            await asyncio.sleep(3600)
