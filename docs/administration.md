# Administration

The **Admin** page is only visible to admin users. It has four tabs: **Overview**, **Users**, **Settings** and **Activity log**.

- [Overview](#overview)
- [Users](#users)
- [Settings](#settings)
- [Environment variables](#environment-variables)
- [What's in /data](#whats-in-data)
- [Disk space](#disk-space)
- [Backups](#backups)
- [Security](#security)
- [Lost the only admin password](#lost-the-only-admin-password)

## Overview

A health table for every stream:

| Column | Meaning |
|---|---|
| Status | Running, reconnecting, failed or stopped |
| Chunks | Audio chunks sent to Whisper since the stream last started |
| Backlog | Chunks waiting for Whisper. If this keeps rising, Whisper can't keep up |
| Last speech | When the stream last produced a line |
| Added by | Who created it |

A red banner appears at the top of the Admin page if `/data` isn't stored on the host; see [Updating](installation.md#updating).

## Users

- **Add** a user with a username, password and optional admin rights.
- **Reset** a user's password.
- **Make or remove admin.**
- **Delete** a user.

Usernames ignore case. Passwords must be at least 8 characters. You can't delete your own account, and the last admin can't lose admin rights.

## Settings

Click **Save settings** at the bottom. Most changes apply to the next chunk; recording settings apply when a stream next starts.

| Setting | Default | What it does |
|---|---|---|
| Whisper URL | `WHISPER_URL`, else `http://192.168.1.10:9000` | Address of your whisper-asr-webservice. **Test** checks it answers |
| Chunk length | 15 s (5–60) | Audio per Whisper request. Shorter means less delay; longer gives Whisper more context and better accuracy |
| Default language | `en` | Used by streams with no language of their own. Blank means auto-detect |
| Silence threshold | 120 | Chunks quieter than this (RMS level) are skipped instead of sent to Whisper. 0 sends everything |
| Simultaneous Whisper requests | 2 (1–8) | Requests in flight across all streams |
| Voice activity filter | On | Strips music and silence before transcribing. Needs the `faster_whisper` or `whisperx` engine; ignored by `openai_whisper` |
| Carry context between chunks | On | Sends the previous line as Whisper's `initial_prompt`, so sentences flow across chunk boundaries |
| Keep transcripts | 30 days | Older lines are deleted. 0 keeps them forever. Lines stay after their audio is deleted |
| Record stream audio | On | Records every stream so lines can be played back |
| Recording quality | 96 kbps | MP3 bitrate: 48 (speech only), 64, 96, 128 or 192 |
| Keep recordings | 7 days | Older audio is deleted hourly, and straight away when you save a shorter time. 0 keeps it forever |

The activity log keeps 14 days.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `WHISPER_URL` | `http://192.168.1.10:9000` | Whisper address on first start only. Afterwards change it in Admin → Settings |
| `TZ` | `Australia/Melbourne` | Time zone for downloaded transcripts and log times |
| `COOKIE_SECURE` | `0` | Set to `1` when the site is only reached over HTTPS |
| `SECRET_KEY` | generated | Signs sign-in cookies. If unset, a key is created once and kept in `/data/secret.key` |
| `DATA_DIR` | `/data` | Where everything is stored |

## What's in /data

```
/data
├── transcriber.db         SQLite: users, streams, transcript lines, settings, logs
├── transcriber.db-wal     SQLite write-ahead log (part of the database)
├── secret.key             cookie signing key (if SECRET_KEY isn't set)
└── audio/
    └── <stream id>/
        └── <recording id>/
            ├── 000000.mp3  one file per minute of a continuous recording
            └── 000001.mp3
```

## Disk space

Recordings take the most space:

| Bitrate | Per stream per day | 7 days |
|---|---|---|
| 96 kbps | about 1 GB | about 7 GB |
| 64 kbps | about 0.7 GB | about 5 GB |

Transcripts are tiny by comparison. Old audio and lines are pruned automatically according to the retention settings. To free space immediately, use **Delete old audio now** in Admin → Settings.

## Backups

Back up the whole `/data` folder. To get a consistent copy of the database, stop the container first, or use SQLite's own backup:

```bash
sqlite3 /mnt/user/appdata/transcriber-2000/transcriber.db ".backup '/mnt/user/backups/transcriber.db'"
```

Unraid's Appdata Backup plugin covers it if `/mnt/user/appdata` is included.

## Security

- Passwords are stored as salted scrypt hashes.
- Eight wrong passwords from one IP within 10 minutes block that IP for 10 minutes.
- Sign-in uses an HTTP-only session cookie, valid for 30 days. Set `COOKIE_SECURE=1` behind HTTPS.
- Every API call that changes something must carry an `X-Requested-With: fetch` header, which other websites can't add. This blocks cross-site request forgery.
- Every page and API call except sign-in, first-run setup and `/healthz` needs a signed-in user. Admin API calls need an admin.

## Lost the only admin password

If no other admin can reset it:

1. Stop the container.
2. Delete `/mnt/user/appdata/transcriber-2000/transcriber.db` and the `-wal` and `-shm` files next to it.
3. Start the container and create a new admin account.

This also deletes streams, transcripts and settings. Recordings in `audio/` are no longer linked to anything; delete that folder too.
