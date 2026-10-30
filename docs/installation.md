# Installation

Audio Transcriber - 2000 is one Docker container. It needs:

- **A Whisper server.** It sends audio to a [whisper-asr-webservice](https://github.com/ahmetoner/whisper-asr-webservice) container's `/asr` endpoint. Any machine on your network will do.
- **A folder for `/data`.** Everything the app keeps lives there.
- **Port 8080** (or any port you map to it).

The image is `linux/amd64`. Pick an image from either registry; they are built from the same code:

- Docker Hub: `haftwo/transcriber-2000:latest`
- GitHub: `ghcr.io/haftwo/transcriber-2000:latest`

- [Unraid](#unraid)
- [Docker Compose](#docker-compose)
- [Plain Docker](#plain-docker)
- [Whisper container settings](#whisper-container-settings)
- [Reaching it from the internet](#reaching-it-from-the-internet)
- [Updating](#updating)
- [Moving from the old stream-transcriber container](#moving-from-the-old-stream-transcriber-container)

## Unraid

### With the template (recommended)

1. Open the Unraid terminal and save the template:
   ```bash
   wget -O /boot/config/plugins/dockerMan/templates-user/my-transcriber-2000.xml \
     https://raw.githubusercontent.com/haftwo/transcriber-2000/main/unraid-template.xml
   ```
2. Go to **Docker → Add Container** and choose **transcriber-2000** from the template list.
3. Set **Whisper URL** to your Whisper container, for example `http://192.168.1.10:9000`. Use the server's LAN IP, not `localhost`.
4. Leave **Data** at `/mnt/user/appdata/transcriber-2000`.
5. Click **Apply**, then open the **WebUI**.

### By hand

**Docker → Add Container**, then set:

| Field | Value |
|---|---|
| Repository | `haftwo/transcriber-2000:latest` |
| Port | Container `8080` → Host `8080` |
| Path | Container `/data` → Host `/mnt/user/appdata/transcriber-2000` |
| Variable | `WHISPER_URL` = `http://<unraid-ip>:9000` |
| Variable (optional) | `TZ` = `Australia/Melbourne` |
| Icon URL (optional) | `https://raw.githubusercontent.com/haftwo/transcriber-2000/main/app/static/icon-512.png` |
| WebUI (optional) | `http://[IP]:[PORT:8080]/` |

## Docker Compose

Use `docker-compose.yml` from this repo (it works with Unraid's Compose Manager plugin too):

```yaml
services:
  transcriber-2000:
    image: haftwo/transcriber-2000:latest
    container_name: transcriber-2000
    restart: unless-stopped
    ports:
      - "8080:8080"
    environment:
      - WHISPER_URL=http://192.168.1.10:9000
      - TZ=Australia/Melbourne
      - COOKIE_SECURE=0
    volumes:
      - /mnt/user/appdata/transcriber-2000:/data
```

```bash
docker compose up -d
```

## Plain Docker

```bash
docker run -d --name transcriber-2000 \
  -p 8080:8080 \
  -v /path/on/host/transcriber-2000:/data \
  -e WHISPER_URL=http://192.168.1.10:9000 \
  -e TZ=Australia/Melbourne \
  --restart unless-stopped \
  haftwo/transcriber-2000:latest
```

## First run

Open `http://<server-ip>:8080`. With no users yet, the sign-in page becomes **Create your admin account**. That account can add users and change settings.

Then go to **Admin → Settings** and press **Test** next to the Whisper URL to confirm the app can reach Whisper.

## Whisper container settings

These work well with whisper-asr-webservice:

| Setting | Recommendation | Why |
|---|---|---|
| `ASR_ENGINE` | `faster_whisper` | Much faster than `openai_whisper`, and needed for the voice-activity filter the app asks for |
| `ASR_MODEL` | `small` or `medium`; `large-v3` if your GPU keeps up | Bigger is more accurate but slower |
| Image | `latest-gpu` with the NVIDIA runtime | Lets the GPU do the work |

Watch **Backlog** on the Admin overview. If it keeps climbing, Whisper can't keep up with the number of streams. Use a smaller model, fewer streams, or raise **Simultaneous Whisper requests** if the GPU has room.

## Reaching it from the internet

The app has its own sign-in and blocks an IP for 10 minutes after repeated wrong passwords. To publish it with a Cloudflare Tunnel:

1. Add a public hostname in the tunnel pointing at `http://<server-ip>:8080`.
2. Set `COOKIE_SECURE=1` on the container so the sign-in cookie is only sent over HTTPS.
3. Consider putting Cloudflare Access in front for a second layer of protection.

The app trusts `X-Forwarded-*` headers, so it works behind any reverse proxy.

## Updating

Your data lives in `/data`, so updating is safe **as long as `/data` is mapped to a folder on the host**:

- **Unraid:** Docker tab → **Check for Updates** → **Apply Update**.
- **Compose:** `docker compose pull && docker compose up -d`.
- **Plain Docker:** pull the new image, remove the container, and run it again with the same `-v` mapping.

Never change or remove the `/data` path when editing the container. If it isn't mapped, the Admin page shows a red warning: **Settings won't survive an update.**

The database upgrades itself on start, so older data keeps working with newer images.

## Moving from the old stream-transcriber container

The app was renamed from `stream-transcriber`. To keep what the old container had, stop it, then either:

- point the new container's `/data` at `/mnt/user/appdata/stream-transcriber`, or
- rename that folder to `transcriber-2000` before starting the new container.
