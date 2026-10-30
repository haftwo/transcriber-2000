# Development

- [Project layout](#project-layout)
- [Running locally](#running-locally)
- [Making changes](#making-changes)
- [Building and releasing](#building-and-releasing)

## Project layout

```
.
├── app/
│   ├── main.py          routes, sign-in, admin API, startup (Starlette)
│   ├── worker.py        per-stream ffmpeg ingest, recording, chunking, Whisper calls, live events
│   ├── db.py            SQLite schema, upgrades, settings, retention, storage check
│   ├── auth.py          scrypt password hashing, login rate limit, session secret
│   └── static/          the three pages, shared JS/CSS, icons (no build step)
│       ├── index.html / app.js       Streams page
│       ├── admin.html / admin.js     Admin page
│       ├── login.html                Sign-in and first-run setup
│       ├── common.js                 API helper, top bar, menus, theme switch
│       ├── style.css                 all styles; light and dark palettes as CSS variables
│       └── favicon.svg, icon-*.png, apple-touch-icon.png, manifest.json
├── docs/                 this documentation
├── .github/workflows/docker.yml     builds and publishes to ghcr.io on push to main
├── Dockerfile
├── docker-compose.yml
├── unraid-template.xml
├── push-to-dockerhub.command       Mac: build and push to Docker Hub with a double-click
└── requirements.txt                 starlette, uvicorn, itsdangerous
```

The server has three Python dependencies and calls Whisper with the standard library. The browser side is plain HTML, CSS and JavaScript with no framework or bundler: edit a file and reload.

## Running locally

You need Python 3.10+ and `ffmpeg` on your PATH.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
DATA_DIR=./data WHISPER_URL=http://192.168.1.10:9000 \
  uvicorn app.main:app --reload --port 8080
```

Open <http://localhost:8080>. `./data` is ignored by git. The "settings won't survive an update" warning only appears inside Docker.

Or run the container from source:

```bash
docker build -t transcriber-2000:dev .
docker run --rm -p 8080:8080 -v "$PWD/data:/data" \
  -e WHISPER_URL=http://192.168.1.10:9000 transcriber-2000:dev
```

## Making changes

- **Theme colours** are CSS variables at the top of `style.css`: the light palette on `:root`, the dark palette repeated for `prefers-color-scheme: dark` and `[data-theme="dark"]`. Change both dark blocks together.
- **The theme choice** is stored in the browser's `localStorage` under `theme` (`light`, `dark`, or absent for Auto). A one-line script in each page's `<head>` applies it before the stylesheet loads, so there is no flash.
- **New settings:** add a default to `DEFAULT_SETTINGS` in `db.py`, a range or check in `api_settings` in `main.py`, and a field in `admin.html`. Existing databases pick up the default on next start.
- **Schema changes:** add the column in `DB.__init__` with an `ALTER TABLE` guarded by a `PRAGMA table_info` check, like the existing upgrades, so old databases keep working.
- **API calls from the browser** go through `api()` in `common.js`, which adds the required `X-Requested-With: fetch` header.

## Building and releasing

There are two ways to publish an image. Both build `linux/amd64` for Unraid.

### GitHub Actions → ghcr.io (automatic)

Every push to `main` runs `.github/workflows/docker.yml`, which publishes:

- `ghcr.io/haftwo/transcriber-2000:latest`
- `ghcr.io/haftwo/transcriber-2000:sha-<short sha>`

Pushing a tag like `v1.2.0` also publishes `:1.2.0`:

```bash
git tag v1.2.0 && git push origin v1.2.0
```

No secrets are needed; it uses the workflow's own `GITHUB_TOKEN`. The first time, check the package is public: GitHub profile → **Packages** → **transcriber-2000** → **Package settings** → **Change visibility**. Otherwise Unraid needs `docker login ghcr.io` with a token that has `read:packages`.

### Docker Hub from a Mac (manual)

With Docker Desktop running, double-click `push-to-dockerhub.command` in Finder. It signs in with Docker Desktop's saved login (account `haftwo` unless Docker reports another, or `DOCKERHUB_USER` is set), then builds and pushes `haftwo/transcriber-2000:latest`.

From a terminal instead:

```bash
docker buildx build --platform linux/amd64 -t haftwo/transcriber-2000:latest --push .
```

### After publishing

Update [CHANGELOG.md](../CHANGELOG.md), then on Unraid: Docker → **Check for Updates** → **Apply Update**.
