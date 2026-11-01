# Changelog

## 1.2.0 — 2026-11-02

### Added

- **Sign in with Microsoft** (Entra ID, formerly Azure AD): Admin → Settings → Sign in with Microsoft takes a tenant, client ID and secret, with a **Test connection** button and the redirect URI to copy. Optional allowed email domains, automatic account creation and button text. Passwords keep working alongside it
- Users linked to a Microsoft account are marked on the Users tab
- `PUBLIC_URL` environment variable, for when the redirect URI behind a proxy doesn't match

### Changed

- Usernames can be up to 100 characters, so email addresses fit

## 1.1.0 — 2026-10-31

### Added

- Video thumbnails: for streams with video, a picture is saved every 5 seconds and shown as a filmstrip along the playback timeline, with a larger preview on hover and click-to-jump
- Admin → Settings → Recording: **Video thumbnails** switch (on by default)
- **Video** and **Audio** headings in the Streams list. Drag streams between them; new streams are filed automatically by whether they have video, or pick a group when adding or editing

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
