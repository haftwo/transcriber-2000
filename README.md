<p align="center">
  <img src="app/static/icon-192.png" width="96" height="96" alt="Audio Transcriber - 2000 icon">
</p>

<h1 align="center">Audio Transcriber - 2000</h1>

<p align="center">
  Live, searchable transcripts of internet radio and audio streams, using your own Whisper server.<br>
  Self-hosted in one Docker container. Built for Unraid, runs anywhere Docker does.
</p>

---

Point it at a live stream (HLS `.m3u8`, Icecast/Shoutcast, most HTTP audio) and it writes down what's said as it's said. Every stream is recorded, so you can click any line to hear that moment again or download it as an MP3.

Transcription is done by a [whisper-asr-webservice](https://github.com/ahmetoner/whisper-asr-webservice) container you run yourself. No audio leaves your network.

## Features

- **Live transcripts** that scroll as people speak, with search and download as `.txt` or `.srt`
- **Play any line back** in a waveform player, widen the clip, and save it as an MP3
- **Many streams at once**, each with its own language, in an order you drag into place
- **Sign-in protected**, with an admin page for users, Whisper settings, stream health and an activity log
- **Light, dark or automatic theme**, remembered per browser
- **Recovers on its own**: dropped streams reconnect, and settings survive container updates
- **No build step**: Python on the server, plain HTML/CSS/JS in the browser

## Quick start

You need Docker and a running whisper-asr-webservice container (port 9000 by default).

```bash
docker run -d --name transcriber-2000 \
  -p 8080:8080 \
  -v /mnt/user/appdata/transcriber-2000:/data \
  -e WHISPER_URL=http://192.168.1.10:9000 \
  -e TZ=Australia/Melbourne \
  --restart unless-stopped \
  haftwo/transcriber-2000:latest
```

Open `http://<server-ip>:8080`. The first visit asks you to create the admin account. Then click **Add** and paste a stream URL.

> **Keep the `/data` mapping.** It holds your settings, users, streams, transcripts and recordings. Without it, they are lost on the next update.

Unraid users: see [Installation → Unraid](docs/installation.md#unraid) for the template.

## Documentation

| Guide | What's in it |
|---|---|
| [Installation](docs/installation.md) | Unraid, Docker Compose, plain Docker, Whisper settings, remote access, updating |
| [Using the app](docs/user-guide.md) | Adding streams, reading and searching transcripts, playback, downloads, themes |
| [Administration](docs/administration.md) | Users, every setting, environment variables, storage, backups |
| [How it works](docs/how-it-works.md) | The audio pipeline, data model and HTTP API |
| [Development](docs/development.md) | Running locally, project layout, building and releasing images |
| [Troubleshooting](docs/troubleshooting.md) | Common problems and fixes |
| [Changelog](CHANGELOG.md) | What changed in each release |

## How it works, in one line

```
stream ──► ffmpeg (16 kHz mono + MP3 recording) ──► 15 s chunks ──► Whisper /asr ──► SQLite ──► browser (live)
```

More in [How it works](docs/how-it-works.md).

## Images

| Registry | Image | Built by |
|---|---|---|
| Docker Hub | `haftwo/transcriber-2000:latest` | `push-to-dockerhub.command` on a Mac |
| GitHub Container Registry | `ghcr.io/haftwo/transcriber-2000:latest` | GitHub Actions, on every push to `main` |

Both are `linux/amd64`.
