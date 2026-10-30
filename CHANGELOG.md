# Changelog

## 1.0.0 — 2026-10-31

First release on GitHub.

### Added

- Live transcription of HLS, Icecast/Shoutcast and HTTP audio streams through a whisper-asr-webservice container
- Sign-in, first-run admin setup, and an Admin page for users, settings, stream health and an activity log
- Recording of every stream, with click-to-play waveform playback and MP3 clip download
- Go to a date and time, transcript search, and `.txt` / `.srt` export
- Drag-to-reorder stream list, shared by all users
- Light, dark and automatic themes, remembered per browser
- App icon, favicon, and home-screen icons for iPhone, iPad and Android
- Warning when `/data` isn't stored on the host, so settings would be lost on update
- Unraid template, Docker Compose file, GitHub Actions build to ghcr.io, and a one-click Docker Hub push script for Mac
- Documentation in `docs/`

### Changed

- Renamed from `stream-transcriber` to `transcriber-2000` (display name "Audio Transcriber - 2000")
