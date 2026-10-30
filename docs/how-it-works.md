# How it works

- [The pipeline](#the-pipeline)
- [Recording and playback](#recording-and-playback)
- [Video thumbnails](#video-thumbnails)
- [Filtering out noise and phantom lines](#filtering-out-noise-and-phantom-lines)
- [Reconnecting](#reconnecting)
- [Live updates in the browser](#live-updates-in-the-browser)
- [Data model](#data-model)
- [HTTP API](#http-api)

## The pipeline

```
                     ┌──► 16 kHz mono PCM ──► 15 s chunks ──► silence check ──► Whisper /asr ──► filter ──► SQLite
stream URL ──► ffmpeg┤                                                                                      │
                     └──► MP3, one file per minute (/data/audio/…)                                          ▼
                                                                                         browser (Server-Sent Events)
```

Each enabled stream has its own worker (`app/worker.py`) running one `ffmpeg` process. ffmpeg pulls the stream and produces two outputs from the same decoded audio:

1. **Raw PCM** (16 kHz, mono, 16-bit) on stdout, which the worker reads.
2. **An MP3 recording**, split into one-minute files.

The worker cuts the PCM into fixed chunks (15 seconds by default), wraps each as a WAV file, and posts it to the Whisper server's `/asr` endpoint with:

- `language`: the stream's language, or the default
- `vad_filter=true`: when the voice activity filter is on
- `initial_prompt`: the last 200 characters of the previous line, when context carrying is on, so sentences continue across chunk boundaries

A shared limit (default 2) caps how many Whisper requests run at once across all streams. Chunks waiting for a slot are the **Backlog** on the Admin page.

Each returned line is stored with its wall-clock time, its duration, and where it sits in the recording.

## Recording and playback

A continuous run of ffmpeg is a **recording** (a "take"). A new one starts every time the stream connects or reconnects. Its audio is in `/data/audio/<stream id>/<recording id>/000000.mp3`, `000001.mp3`, … each 60 seconds long.

Both outputs come from the same ffmpeg process with timestamps rebuilt from the sample count (`asetpts=N/SR/TB`), so a line's offset into the recording stays exact for the life of the take. Playback can't drift from the transcript.

To play a clip, the browser asks for `/api/streams/<id>/audio?rec=…&start=…&end=…`. The server finds the minute files that cover that range and has ffmpeg cut and join them into one MP3. Clips are limited to 15 minutes.

## Video thumbnails

When a stream starts, the worker runs `ffprobe` on it once to see whether it has a video track. The same check files a new stream under **Video** or **Audio** in the sidebar if no group was chosen. If it does, and **Video thumbnails** is on, ffmpeg gets a third output:

```
-skip_frame:v nokey   (input)   decode keyframes only, so this costs almost no CPU
-map 0:v:0 -vf setpts=PTS-STARTPTS,fps=1/5:round=up,scale=-2:144  →  thumbs/%06d.jpg
```

`thumbs/000000.jpg` is the start of the take and file *n* is *n* × 5 seconds in. `round=up` makes each picture the last keyframe at or before its moment, so it is never ahead of the audio; with typical 1–2 second keyframe spacing it is within a second or two. The take's `thumb_seconds` column records the interval (0 for audio-only takes).

The player asks `/api/streams/<id>/thumbs` which pictures exist for the clip, then lays out enough of them to fill the filmstrip. Thumbnails are pruned along with the audio.

## Filtering out noise and phantom lines

Whisper tends to invent text when given music or silence. Three layers stop that reaching the transcript:

1. **Silence check:** chunks whose RMS level is below the silence threshold (default 120) are never sent.
2. **Voice activity filter:** faster-whisper strips non-speech before transcribing.
3. **Phantom-line filter:** results are dropped if they are one of Whisper's well-known stock phrases on silence ("Thank you.", "Thanks for watching", "Please subscribe" and similar), only bracketed sound cues such as `[Music]` or `(applause)`, or one short word repeated six or more times.

## Reconnecting

If ffmpeg exits (the stream dropped, the URL expired, the network blipped), the worker logs why and retries after 5 seconds, doubling the wait each time up to 2 minutes. A successful connection resets the wait. ffmpeg's own HTTP reconnect handles brief interruptions without a restart.

On container start, every enabled stream starts again automatically.

An hourly housekeeping task deletes transcript lines, recordings and log entries older than their retention periods.

## Live updates in the browser

The browser holds one Server-Sent Events connection to `/api/events`. The server pushes:

| Event `type` | When |
|---|---|
| `segment` | A new transcript line |
| `status` | A stream's state or counters changed |
| `order` | Someone reordered or regrouped the stream list |
| `category` | A stream moved group, or was filed automatically after the video check |
| `deleted` | A stream was deleted |

A comment ping is sent every 15 seconds so proxies keep the connection open, and the browser reconnects after 3 seconds if it drops.

## Data model

SQLite in WAL mode, at `/data/transcriber.db`. Missing columns are added on start, so older databases upgrade themselves.

| Table | Holds |
|---|---|
| `users` | `username` (case-insensitive, unique), scrypt `pw_hash`, `is_admin`, `created` |
| `streams` | `name`, `url`, `language`, `enabled`, `created_by`, `created`, `position` (list order), `category` (`video`, `audio`, or blank until the first check) |
| `segments` | One transcript line: `stream_id`, `ts` (unix time), `duration`, `text`, `rec_id`, `rec_offset` (seconds into the recording) |
| `recordings` | One take: `stream_id`, `started`, `length`, `seg_seconds`, `thumb_seconds` (0 = no video thumbnails) |
| `settings` | Key/value pairs; see [Administration](administration.md#settings) |
| `logs` | Activity log: `ts`, `level`, `stream_id`, `message` (kept 14 days) |

Deleting a stream deletes its lines, recordings and audio files.

## HTTP API

The web pages use a small JSON API. It's documented here for scripting and troubleshooting; it isn't a stable public interface.

**Authentication** is the session cookie set by `/api/login`. **Changes** (`POST`, `PUT`, `PATCH`, `DELETE`) must send `X-Requested-With: fetch`, or they are refused with 403. **Errors** come back as `{"error": "message"}` with a 4xx status.

### Pages and health

| Method & path | Auth | Returns |
|---|---|---|
| `GET /` | user | Streams page (redirects to `/login` if signed out) |
| `GET /login` | — | Sign-in page |
| `GET /admin` | admin | Admin page (others are sent to `/`) |
| `GET /healthz` | — | `ok`; used by the Docker health check |

### Account

| Method & path | Auth | Body / query | Notes |
|---|---|---|---|
| `GET /api/setup` | — | | `{"needs_setup": true}` when there are no users yet |
| `POST /api/setup` | — | `{username, password}` | Creates the first admin; only works once |
| `POST /api/login` | — | `{username, password}` | Rate limited per IP |
| `POST /api/logout` | user | | |
| `GET /api/me` | user | | `{id, username, is_admin, created}` |
| `POST /api/me/password` | user | `{current, new}` | |

### Streams and transcripts

| Method & path | Auth | Body / query | Notes |
|---|---|---|---|
| `GET /api/streams` | user | | All streams in list order, with live status |
| `POST /api/streams` | user | `{name, url, language?, category?}` | Adds and starts a stream. `category` is `video`, `audio`, or blank to decide automatically |
| `GET /api/streams/{id}` | user | | One stream |
| `PATCH /api/streams/{id}` | user | `{name?, url?, language?, category?, enabled?, restart?}` | Restarts if URL or language changed, or `restart` is true |
| `DELETE /api/streams/{id}` | user | | Deletes it with its transcript and audio |
| `PUT /api/streams/order` | user | `{ids: [3, 1, 2], categories?: {"3": "video"}}` | Saves the list order, top to bottom, and moves streams between the Video and Audio groups |
| `GET /api/streams/{id}/segments` | user | `limit` (≤ 500), `before`, `after`, `at`, `q` | Latest lines by default. `before`/`after` page by line id; `at` (unix time) returns lines around that moment plus the recording covering it; `q` filters by text |
| `GET /api/streams/{id}/export` | user | `format=txt\|srt`, `hours` (default 24) | Transcript download |
| `GET /api/streams/{id}/audio` | user | `rec`, `start`, `end` (seconds into the recording) | MP3 clip, up to 15 minutes |
| `GET /api/streams/{id}/thumbs` | user | `rec`, `start`, `end` | `{interval, n: [...]}`: which video thumbnails exist in that range (`interval` 0 = no video) |
| `GET /api/streams/{id}/thumbs/{rec}/{n}.jpg` | user | | One thumbnail, *n* × `interval` seconds into the recording |
| `GET /api/events` | user | | Server-Sent Events stream |

### Admin

| Method & path | Auth | Body | Notes |
|---|---|---|---|
| `GET /api/admin/users` | admin | | |
| `POST /api/admin/users` | admin | `{username, password, is_admin?}` | |
| `PATCH /api/admin/users/{id}` | admin | `{password?, is_admin?}` | |
| `DELETE /api/admin/users/{id}` | admin | | Not your own account |
| `GET /api/admin/settings` | admin | | All settings |
| `PUT /api/admin/settings` | admin | `{key: value, …}` | Validated and range-checked |
| `POST /api/admin/test-whisper` | admin | `{whisper_url?}` | Sends one second of silence to Whisper and reports whether it answered |
| `POST /api/admin/prune-audio` | admin | | Deletes audio past its retention now |
| `GET /api/admin/logs` | admin | `limit` (≤ 1000) | Activity log, newest first |
| `GET /api/admin/stats` | admin | | Counts, database size, audio size, storage warning |

### Example: export a transcript with curl

```bash
# sign in and keep the cookie
curl -c jar -H 'X-Requested-With: fetch' -H 'Content-Type: application/json' \
  -d '{"username":"joe","password":"…"}' http://server:8080/api/login

# last 7 days of stream 1 as text
curl -b jar -o stream1.txt 'http://server:8080/api/streams/1/export?format=txt&hours=168'
```
