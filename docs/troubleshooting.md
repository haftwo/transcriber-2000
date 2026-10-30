# Troubleshooting

Start with **Admin → Activity log**: most problems show up there with a reason. The container's own log (Unraid: Docker → transcriber-2000 → **Logs**) shows the same messages.

## A stream says Error or keeps reconnecting

- **The URL has expired.** Many stations sign their stream URLs and the signature lapses after a few hours. Get a fresh URL ([how](user-guide.md#finding-a-stream-url)), then **Edit stream**.
- **The station blocks the server.** Some streams are geo-blocked or need headers a browser sends. Check the URL plays in VLC on the same network.
- **It's not a stream URL.** A link to the station's web page won't work; you need the `.m3u8` playlist or direct audio URL.

The worker retries with a growing wait, up to 2 minutes between attempts, so a stream that comes back will recover on its own.

## No lines appear, but the stream is live

1. **Admin → Settings → Test** next to the Whisper URL. If it can't connect, check the address. Use the server's LAN IP, not `localhost`, which means the transcriber container itself.
2. **Check the Backlog** on the Admin overview. If it's climbing, Whisper is too slow; see below.
3. **The audio may be too quiet.** Lower the **Silence threshold**, or set it to 0 to send everything.
4. **The language may be wrong.** A stream set to `en` that's actually in another language can produce nothing useful. Set its language, or leave it blank to auto-detect.

## Lines arrive late, or the backlog keeps growing

Whisper isn't keeping up. In order of effect:

- Run Whisper on a GPU (`latest-gpu` image, NVIDIA runtime).
- Use `ASR_ENGINE=faster_whisper`.
- Use a smaller model (`small` instead of `medium` or `large-v3`).
- Raise **Simultaneous Whisper requests** if the GPU has headroom.
- Run fewer streams.

A shorter **Chunk length** lowers delay but doesn't reduce the total work.

## Music turns into nonsense lines

Make sure the **Voice activity filter** is on and Whisper uses `faster_whisper` or `whisperx`; the filter is ignored by `openai_whisper`. Common phantom phrases are filtered already. Raising the **Silence threshold** a little can also help.

## "Settings won't survive an update"

`/data` isn't mapped to a folder on the server, so everything will be lost when the container is updated. Edit the container and add a path: container `/data` → host `/mnt/user/appdata/transcriber-2000`. See [Updating](installation.md#updating).

## Listen doesn't play

The station blocks playback from other websites (CORS) or the browser can't play HLS directly. Transcription and recorded playback still work, because the server fetches the audio itself.

## A line won't play back

Its audio has passed the **Keep recordings** period, or recording was off when it was transcribed. The transcript line stays until **Keep transcripts** expires.

## Signed out unexpectedly, or can't stay signed in

- Behind HTTPS (Cloudflare Tunnel or a reverse proxy) set `COOKIE_SECURE=1`. Over plain `http://`, set it to `0`, or the browser drops the cookie.
- Sessions are signed with `/data/secret.key`. If `/data` isn't persistent, a new key is made on each update and everyone is signed out.

## "Too many attempts"

Eight wrong passwords from one IP within 10 minutes block it for 10 minutes. Wait, or restart the container to clear the block.

## The new icon or theme doesn't show after an update

Browsers cache icons and stylesheets. Hard-refresh (**⇧⌘R** on a Mac, **Ctrl+Shift+R** on Windows), or close and reopen the tab. For a home-screen shortcut, remove and add it again.

## Forgot the admin password

Another admin can reset it in **Admin → Users**. If there's no other admin, see [Lost the only admin password](administration.md#lost-the-only-admin-password).
