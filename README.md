# Stream Transcriber

A small self-hosted web app that listens to live internet audio streams (HLS `.m3u8`, Icecast/Shoutcast, most HTTP audio) and shows a live, searchable transcript using your existing **whisper-asr-webservice** container.

- Sign-in page (first visit creates the admin account)
- Streams page: add/edit/stop streams, live transcript that scrolls as people speak, search, "Listen" to play along, download as `.txt` or `.srt`
- Admin page: users, Whisper settings (with a connection test), stream health, activity log
- Everything stored in one SQLite file in `/data`

## How it works

```
HLS stream ──► ffmpeg (16 kHz mono) ──► 15 s chunks ──► whisper-asr-webservice /asr ──► SQLite ──► browser (live via SSE)
```

Each stream runs its own ffmpeg process. Audio is cut into fixed chunks (default 15 s); near-silent chunks are skipped and Whisper's common phantom lines on music ("Thank you.", "[Music]") are dropped. The previous line is passed as `initial_prompt` so sentences carry across chunk boundaries. If a stream drops, it reconnects automatically with back-off.

## Install on Unraid

The image is built by GitHub and published to GitHub Container Registry, so Unraid just pulls it.

### 1. Publish the image (one-off)

1. Create a new repo on GitHub called `stream-transcriber`. Public is simplest: the image is then public too and Unraid can pull it without a login.
2. Push this folder to it:
   ```bash
   cd stream-transcriber
   git remote add origin https://github.com/YOUR-GITHUB-USERNAME/stream-transcriber.git
   git push -u origin main
   ```
3. Watch the **Actions** tab. After about 2–3 minutes the image is at
   `ghcr.io/YOUR-GITHUB-USERNAME/stream-transcriber:latest`.
4. **Private repo?** The package will be private too. Either make the package public (your GitHub profile → Packages → stream-transcriber → Package settings → Change visibility), or log Unraid in once from its terminal with a GitHub token that has `read:packages`:
   `docker login ghcr.io -u YOUR-GITHUB-USERNAME`

Every later `git push` to `main` rebuilds `:latest`. On Unraid, use **Check for Updates** → **Apply Update** to pull it.

### 2. Run it on Unraid

**Template (recommended):** edit `unraid-template.xml` and replace `YOUR-GITHUB-USERNAME`. Then, from the Unraid terminal:
```bash
nano /boot/config/plugins/dockerMan/templates-user/my-stream-transcriber.xml   # paste the template
```
Go to the Docker tab → *Add Container* → choose **stream-transcriber** → set *Whisper URL* → *Apply*.

**Or, without a template:** Docker tab → *Add Container*, then set:
- Repository `ghcr.io/YOUR-GITHUB-USERNAME/stream-transcriber:latest`
- Port 8080 → 8080
- Path `/data` → `/mnt/user/appdata/stream-transcriber`
- Variable `WHISPER_URL` = `http://<unraid-ip>:9000`

**Compose Manager plugin:** use `docker-compose.yml`, with your username filled in.

Then open `http://<unraid-ip>:8080` and create your admin account.

### Alternative: Docker Hub instead of GitHub

From the Unraid terminal, inside this folder:
```bash
docker login                     # Docker Hub username + access token
docker build -t YOUR-DOCKERHUB-USER/stream-transcriber:latest .
docker push YOUR-DOCKERHUB-USER/stream-transcriber:latest
```

### Whisper container settings that work well

- `ASR_ENGINE=faster_whisper` — much faster than `openai_whisper`, and needed for the voice-activity filter.
- `ASR_MODEL=small` or `medium` for one or two streams on a GPU; `large-v3` if the GPU keeps up (watch **Backlog** on the Admin page — if it climbs, Whisper is too slow for the number of streams).
- Use the `latest-gpu` image with the NVIDIA runtime so your GPU does the work.

## Putting it on the internet (Cloudflare Tunnel)

Add a public hostname in your tunnel pointing at `http://<unraid-ip>:8080`, then set `COOKIE_SECURE=1` on the container so the sign-in cookie is only sent over HTTPS. Repeated wrong passwords from one IP are blocked for 10 minutes. Consider adding Cloudflare Access in front for a second layer.

## Finding a stream URL

Open the station's web player, open browser dev tools → **Network**, filter for `m3u8`, press play, and copy the URL of the playlist (`…/master.m3u8` or `…/playlist.m3u8`). Some stations use signed URLs that expire; if a stream errors after a few hours, grab a fresh URL. "Listen" in the browser may not work for stations that block cross-site playback — transcription still works because the server fetches the audio itself.

## Settings (Admin → Settings)

| Setting | Default | Notes |
|---|---|---|
| Whisper URL | from `WHISPER_URL` | Test button checks it's reachable |
| Chunk length | 15 s | Shorter = less delay, longer = more accurate |
| Default language | `en` | Blank = auto-detect. Each stream can override |
| Silence threshold | 120 | RMS level below which a chunk is skipped |
| Simultaneous Whisper requests | 2 | Across all streams |
| Keep transcripts | 30 days | 0 = forever |

## Environment variables

| Variable | Purpose |
|---|---|
| `WHISPER_URL` | Initial Whisper address (afterwards edit in Admin) |
| `TZ` | Time zone for downloaded transcripts |
| `COOKIE_SECURE` | `1` when served only over HTTPS |
| `SECRET_KEY` | Optional; otherwise a key is generated and kept in `/data/secret.key` |
| `DATA_DIR` | Defaults to `/data` |

## Forgot the admin password?

Stop the container and delete `/mnt/user/appdata/stream-transcriber/transcriber.db` to start fresh (this also removes streams and transcripts), or ask another admin to reset it from Admin → Users.

## Running locally for development

```bash
pip install -r requirements.txt
DATA_DIR=./data WHISPER_URL=http://192.168.1.10:9000 uvicorn app.main:app --reload --port 8080
```

## Files

```
app/main.py        routes, auth, admin API
app/worker.py      ffmpeg ingest, chunking, Whisper calls, live event fan-out
app/db.py          SQLite schema and settings
app/auth.py        password hashing (scrypt) and login rate limit
app/static/        login, streams and admin pages (plain HTML/CSS/JS, no build step)
```
