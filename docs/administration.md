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

People who sign in with Microsoft show **· Microsoft** next to their role. Reset password gives them a password as well, if you want them to have both.

Usernames ignore case and can be up to 100 characters, so email addresses work. Passwords must be at least 8 characters. You can't delete your own account, and the last admin can't lose admin rights.

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
| Video thumbnails | On | For streams with video, saves a picture every 5 seconds for the player's filmstrip. Applies when a stream next starts |
| Keep recordings | 7 days | Older audio is deleted hourly, and straight away when you save a shorter time. 0 keeps it forever |

The activity log keeps 14 days.

## Sign in with Microsoft (Entra ID / Azure AD)

Lets people sign in with their Microsoft work or school account. Username and password sign-in keeps working alongside it, so you can't lock yourself out.

### 1. Register the app in Azure

1. In the [Azure portal](https://portal.azure.com), open **Microsoft Entra ID → App registrations → New registration**.
2. Name it (for example *Audio Transcriber - 2000*). Under **Supported account types**, choose **Accounts in this organizational directory only**.
3. Under **Redirect URI**, pick **Web** and paste the **Redirect URI** shown in Admin → Settings → Sign in with Microsoft. It's `https://<your-address>/auth/microsoft/callback`. Microsoft only accepts `https://`, except for `http://localhost`.
4. Click **Register**. From the **Overview** page, copy the **Application (client) ID** and **Directory (tenant) ID**.
5. Open **Certificates & secrets → New client secret**. Copy the secret's **Value** straight away; Azure only shows it once. Note the expiry date: sign-in stops working when it expires, so set a reminder to make a new one.

No API permissions are needed beyond the default *User.Read*.

### 2. Turn it on

In **Admin → Settings → Sign in with Microsoft**, paste the tenant ID, client ID and secret, click **Test connection**, tick **Turn on Microsoft sign-in**, then **Save settings**. A **Sign in with Microsoft** button appears on the sign-in page.

| Setting | Default | What it does |
|---|---|---|
| Directory (tenant) ID | — | Your tenant's ID, or one of its verified domains (`contoso.com`). `common`, `organizations` and `consumers` aren't accepted, because they'd let any Microsoft account in |
| Application (client) ID | — | From the app registration's Overview page |
| Client secret | — | The secret's **Value**. Stored in the database on `/data` and never sent back to the browser; leave the box blank to keep the saved one |
| Allowed email domains | blank | Comma-separated, e.g. `contoso.com, fabrikam.com`. Blank lets anyone in the tenant sign in |
| Button text | Sign in with Microsoft | The label on the sign-in page |
| Create accounts automatically | On | A first-time Microsoft sign-in creates a regular (non-admin) user named after their sign-in name, e.g. `jo@contoso.com`. Promote them on the Users tab. When off, add the user first with that sign-in name as the username |
| Turn on Microsoft sign-in | Off | Shows the button. Can only be turned on once the tenant, client ID and secret are filled in |

### How accounts are matched

- The first time someone signs in with Microsoft, they're linked to the user with the same username (their sign-in name, in lower case), or a new user is created.
- After that they're matched by their Microsoft account's ID, so renaming them in Entra doesn't create a second user.
- A username already linked to one Microsoft account can't be taken over by a different one.
- To restrict who can sign in more tightly, in Entra open **Enterprise applications → your app → Properties**, set **Assignment required** to **Yes**, and assign users or groups under **Users and groups**.

### The redirect URI has to match exactly

The app builds the redirect URI from the address the browser used. If you reach the app through a reverse proxy or Cloudflare Tunnel and Microsoft says the redirect URI doesn't match, set the `PUBLIC_URL` environment variable to the address people use (for example `https://transcriber.example.com`) and register `PUBLIC_URL/auth/microsoft/callback` in Azure.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `WHISPER_URL` | `http://192.168.1.10:9000` | Whisper address on first start only. Afterwards change it in Admin → Settings |
| `TZ` | `Australia/Melbourne` | Time zone for downloaded transcripts and log times |
| `COOKIE_SECURE` | `0` | Set to `1` when the site is only reached over HTTPS |
| `SECRET_KEY` | generated | Signs sign-in cookies. If unset, a key is created once and kept in `/data/secret.key` |
| `DATA_DIR` | `/data` | Where everything is stored |
| `PUBLIC_URL` | blank | The address people use to reach the app, e.g. `https://transcriber.example.com`. Only needed if Microsoft sign-in reports a redirect URI mismatch |

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
            ├── 000001.mp3
            └── thumbs/     video streams only: 000000.jpg, 000001.jpg … one every 5 s
```

## Disk space

Recordings take the most space:

| Bitrate | Per stream per day | 7 days |
|---|---|---|
| 96 kbps | about 1 GB | about 7 GB |
| 64 kbps | about 0.7 GB | about 5 GB |

Video thumbnails add roughly 0.1 GB per video stream per day. Transcripts are tiny by comparison. Old audio and lines are pruned automatically according to the retention settings. To free space immediately, use **Delete old audio now** in Admin → Settings.

## Backups

Back up the whole `/data` folder. To get a consistent copy of the database, stop the container first, or use SQLite's own backup:

```bash
sqlite3 /mnt/user/appdata/transcriber-2000/transcriber.db ".backup '/mnt/user/backups/transcriber.db'"
```

Unraid's Appdata Backup plugin covers it if `/mnt/user/appdata` is included.

## Security

- Passwords are stored as salted scrypt hashes.
- Microsoft sign-in uses OpenID Connect with PKCE, state and nonce. The ID token comes directly from Microsoft over HTTPS and its issuer, audience, expiry and nonce are checked. Only one tenant is trusted. Users created by Microsoft sign-in have no password until an admin sets one.
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
