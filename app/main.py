"""Stream Transcriber — web app entry point (Starlette + Uvicorn)."""
import asyncio
import contextlib
import json
import os
import re
import time
import urllib.error

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import (FileResponse, JSONResponse, PlainTextResponse,
                                 RedirectResponse, Response, StreamingResponse)
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .auth import RateLimiter, hash_password, load_secret, verify_password
from .db import DATA_DIR, DB, DEFAULT_SETTINGS
from .worker import Manager, pcm_to_wav, whisper_request

STATIC = os.path.join(os.path.dirname(__file__), "static")
db = DB()
manager = Manager(db)
limiter = RateLimiter()


# helpers --------------------------------------------------------------------
def current_user(request: Request):
    uid = request.session.get("uid")
    if not uid:
        return None
    return db.one("SELECT id, username, is_admin, created FROM users WHERE id=?", (uid,))


def need_user(request):
    user = current_user(request)
    if not user:
        raise HTTPException(401, "Please sign in")
    return user


def need_admin(request):
    user = need_user(request)
    if not user["is_admin"]:
        raise HTTPException(403, "Admins only")
    return user


async def body(request):
    try:
        data = await request.json()
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(400, "Invalid JSON")
    if not isinstance(data, dict):
        raise HTTPException(400, "Invalid JSON")
    return data


def clean_url(url):
    url = (url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(400, "Stream URL must start with http:// or https://")
    if len(url) > 2000 or any(c.isspace() for c in url):
        raise HTTPException(400, "That doesn't look like a valid URL")
    return url


def clean_lang(lang):
    lang = (lang or "").strip().lower()
    if lang and (len(lang) > 5 or not lang.replace("-", "").isalpha()):
        raise HTTPException(400, "Language should be a code like 'en', or blank for auto")
    return lang


def check_username(name):
    name = (name or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._@-]{2,40}", name):
        raise HTTPException(400, "Usernames are 2-40 letters, numbers, dots, dashes or underscores")
    return name


def check_password(pw):
    if len(pw or "") < 8:
        raise HTTPException(400, "Password must be at least 8 characters")


def stream_out(s):
    last = db.one("SELECT text, ts, duration FROM segments WHERE stream_id=? ORDER BY id DESC LIMIT 1", (s["id"],))
    out = {**s, **manager.info(s["id"])}
    out["last_text"] = last["text"] if last else None
    out["last_text_at"] = out["last_text_at"] or (last["ts"] + last["duration"] if last else None)
    return out


# pages ------------------------------------------------------------------------
async def page_index(request):
    if not current_user(request):
        return RedirectResponse("/login", 303)
    return FileResponse(os.path.join(STATIC, "index.html"))


async def page_login(request):
    if current_user(request):
        return RedirectResponse("/", 303)
    return FileResponse(os.path.join(STATIC, "login.html"))


async def page_admin(request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", 303)
    if not user["is_admin"]:
        return RedirectResponse("/", 303)
    return FileResponse(os.path.join(STATIC, "admin.html"))


async def health(request):
    return PlainTextResponse("ok")


# auth -------------------------------------------------------------------------
async def api_setup_status(request):
    return JSONResponse({"needs_setup": db.one("SELECT COUNT(*) n FROM users")["n"] == 0})


async def api_setup(request):
    if db.one("SELECT COUNT(*) n FROM users")["n"]:
        raise HTTPException(409, "Setup is already complete")
    data = await body(request)
    username = check_username(data.get("username"))
    check_password(data.get("password"))
    uid = db.x("INSERT INTO users(username, pw_hash, is_admin, created) VALUES (?, ?, 1, ?)",
               (username, hash_password(data["password"]), time.time()))
    request.session["uid"] = uid
    db.log("info", f"Admin account '{username}' created")
    return JSONResponse({"ok": True})


async def api_login(request):
    ip = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")
    if limiter.blocked(ip):
        raise HTTPException(429, "Too many attempts. Try again in a few minutes.")
    data = await body(request)
    row = db.one("SELECT * FROM users WHERE username=?", ((data.get("username") or "").strip(),))
    if not row or not verify_password(data.get("password") or "", row["pw_hash"]):
        limiter.fail(ip)
        db.log("warning", f"Failed sign-in for '{data.get('username', '')}' from {ip}")
        raise HTTPException(401, "Incorrect username or password")
    limiter.reset(ip)
    request.session.clear()
    request.session["uid"] = row["id"]
    return JSONResponse({"ok": True})


async def api_logout(request):
    request.session.clear()
    return JSONResponse({"ok": True})


async def api_me(request):
    return JSONResponse(need_user(request))


async def api_change_password(request):
    user = need_user(request)
    data = await body(request)
    row = db.one("SELECT pw_hash FROM users WHERE id=?", (user["id"],))
    if not verify_password(data.get("current") or "", row["pw_hash"]):
        raise HTTPException(400, "Current password is incorrect")
    check_password(data.get("new"))
    db.x("UPDATE users SET pw_hash=? WHERE id=?", (hash_password(data["new"]), user["id"]))
    return JSONResponse({"ok": True})


# streams ----------------------------------------------------------------------
async def api_streams(request):
    user = need_user(request)
    if request.method == "GET":
        rows = db.q("SELECT * FROM streams ORDER BY name COLLATE NOCASE")
        return JSONResponse([stream_out(s) for s in rows])
    data = await body(request)
    name = (data.get("name") or "").strip()[:80]
    if not name:
        raise HTTPException(400, "Give the stream a name")
    url, lang = clean_url(data.get("url")), clean_lang(data.get("language"))
    sid = db.x("INSERT INTO streams(name, url, language, enabled, created_by, created) "
               "VALUES (?, ?, ?, 1, ?, ?)", (name, url, lang, user["username"], time.time()))
    db.log("info", f"{user['username']} added stream '{name}'", sid)
    await manager.start(sid)
    return JSONResponse(stream_out(db.one("SELECT * FROM streams WHERE id=?", (sid,))), 201)


async def api_stream(request):
    user = need_user(request)
    sid = request.path_params["sid"]
    s = db.one("SELECT * FROM streams WHERE id=?", (sid,))
    if not s:
        raise HTTPException(404, "Stream not found")
    if request.method == "GET":
        return JSONResponse(stream_out(s))
    if request.method == "DELETE":
        await manager.stop(sid)
        db.x("DELETE FROM segments WHERE stream_id=?", (sid,))
        db.x("DELETE FROM streams WHERE id=?", (sid,))
        db.log("info", f"{user['username']} deleted stream '{s['name']}'")
        manager.broker.publish({"type": "deleted", "stream_id": sid})
        return JSONResponse({"ok": True})

    data = await body(request)
    name = (data.get("name", s["name"]) or "").strip()[:80] or s["name"]
    url = clean_url(data["url"]) if "url" in data else s["url"]
    lang = clean_lang(data["language"]) if "language" in data else s["language"]
    enabled = int(bool(data.get("enabled", s["enabled"])))
    db.x("UPDATE streams SET name=?, url=?, language=?, enabled=? WHERE id=?",
         (name, url, lang, enabled, sid))
    changed = url != s["url"] or lang != s["language"]
    if enabled and (changed or not s["enabled"] or data.get("restart")):
        await manager.start(sid)
        db.log("info", f"{user['username']} started stream", sid)
    elif not enabled and s["enabled"]:
        await manager.stop(sid)
        db.log("info", f"{user['username']} stopped stream", sid)
    return JSONResponse(stream_out(db.one("SELECT * FROM streams WHERE id=?", (sid,))))


async def api_segments(request):
    need_user(request)
    sid = request.path_params["sid"]
    qp = request.query_params
    limit = min(int(qp.get("limit", 150)), 500)
    where, args = ["stream_id=?"], [sid]
    if qp.get("before"):
        where.append("id < ?")
        args.append(int(qp["before"]))
    if qp.get("q"):
        where.append("text LIKE ?")
        args.append("%" + qp["q"].replace("%", "").replace("_", "") + "%")
    rows = db.q(f"SELECT id, ts, duration, text FROM segments WHERE {' AND '.join(where)} "
                f"ORDER BY id DESC LIMIT ?", (*args, limit))
    rows.reverse()
    return JSONResponse({"segments": rows, "more": len(rows) == limit})


def _srt_time(sec):
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


async def api_export(request):
    need_user(request)
    sid = request.path_params["sid"]
    s = db.one("SELECT name FROM streams WHERE id=?", (sid,))
    if not s:
        raise HTTPException(404, "Stream not found")
    hours = float(request.query_params.get("hours", 24))
    fmt = request.query_params.get("format", "txt")
    rows = db.q("SELECT ts, duration, text FROM segments WHERE stream_id=? AND ts>=? ORDER BY ts",
                (sid, time.time() - hours * 3600))
    safe = "".join(c if c.isalnum() else "-" for c in s["name"]).strip("-") or "stream"
    if fmt == "srt" and rows:
        t0 = rows[0]["ts"]
        out = "\n".join(
            f"{i}\n{_srt_time(r['ts'] - t0)} --> {_srt_time(r['ts'] - t0 + r['duration'])}\n{r['text']}\n"
            for i, r in enumerate(rows, 1))
    else:
        fmt = "txt"
        out = "\n".join(time.strftime("[%Y-%m-%d %H:%M:%S] ", time.localtime(r["ts"])) + r["text"]
                        for r in rows)
    return Response(out, media_type="text/plain; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="{safe}-{time.strftime("%Y%m%d-%H%M")}.{fmt}"'})


async def api_events(request):
    need_user(request)
    q = manager.broker.subscribe()

    async def gen():
        try:
            yield "retry: 3000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(ev)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            manager.broker.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


# admin ------------------------------------------------------------------------
async def api_users(request):
    admin = need_admin(request)
    if request.method == "GET":
        return JSONResponse(db.q("SELECT id, username, is_admin, created FROM users ORDER BY username"))
    data = await body(request)
    username = check_username(data.get("username"))
    check_password(data.get("password"))
    if db.one("SELECT id FROM users WHERE username=?", (username,)):
        raise HTTPException(409, "That username is taken")
    db.x("INSERT INTO users(username, pw_hash, is_admin, created) VALUES (?, ?, ?, ?)",
         (username, hash_password(data["password"]), int(bool(data.get("is_admin"))), time.time()))
    db.log("info", f"{admin['username']} created user '{username}'")
    return JSONResponse({"ok": True}, 201)


async def api_user(request):
    admin = need_admin(request)
    uid = request.path_params["uid"]
    u = db.one("SELECT * FROM users WHERE id=?", (uid,))
    if not u:
        raise HTTPException(404, "User not found")
    admins = db.one("SELECT COUNT(*) n FROM users WHERE is_admin=1")["n"]
    if request.method == "DELETE":
        if uid == admin["id"]:
            raise HTTPException(400, "You can't delete your own account")
        db.x("DELETE FROM users WHERE id=?", (uid,))
        db.log("info", f"{admin['username']} deleted user '{u['username']}'")
        return JSONResponse({"ok": True})
    data = await body(request)
    if "is_admin" in data:
        new = int(bool(data["is_admin"]))
        if not new and u["is_admin"] and admins <= 1:
            raise HTTPException(400, "There must be at least one admin")
        db.x("UPDATE users SET is_admin=? WHERE id=?", (new, uid))
    if data.get("password"):
        check_password(data["password"])
        db.x("UPDATE users SET pw_hash=? WHERE id=?", (hash_password(data["password"]), uid))
        db.log("info", f"{admin['username']} reset the password for '{u['username']}'")
    return JSONResponse({"ok": True})


async def api_settings(request):
    need_admin(request)
    if request.method == "GET":
        return JSONResponse(db.settings())
    data = await body(request)
    numeric = {"chunk_seconds": (5, 60), "silence_threshold": (0, 5000),
               "retention_days": (0, 3650), "max_concurrent": (1, 8),
               "vad_filter": (0, 1), "use_prompt": (0, 1)}
    for key, val in data.items():
        if key not in DEFAULT_SETTINGS:
            continue
        if key in numeric:
            try:
                n = float(val)
            except (TypeError, ValueError):
                raise HTTPException(400, f"{key} must be a number")
            lo, hi = numeric[key]
            val = str(int(min(max(n, lo), hi)))
        elif key == "whisper_url":
            val = clean_url(val).rstrip("/")
        elif key == "default_language":
            val = clean_lang(val)
        db.set_setting(key, val)
    return JSONResponse(db.settings())


async def api_test_whisper(request):
    need_admin(request)
    data = await body(request)
    url = clean_url(data.get("whisper_url") or db.setting("whisper_url"))
    silence = pcm_to_wav(b"\x00\x00" * 16000)  # one second of silence
    t0 = time.time()
    try:
        await asyncio.to_thread(whisper_request, url, silence, "en", "", False, 60)
    except urllib.error.HTTPError as e:
        return JSONResponse({"ok": False, "message": f"Whisper replied HTTP {e.code}: {e.reason}"})
    except (urllib.error.URLError, OSError) as e:
        return JSONResponse({"ok": False, "message": f"Can't reach Whisper: {getattr(e, 'reason', e)}"})
    return JSONResponse({"ok": True, "message": f"Connected — Whisper answered in {time.time() - t0:.1f}s"})


async def api_logs(request):
    need_admin(request)
    limit = min(int(request.query_params.get("limit", 200)), 1000)
    rows = db.q("SELECT l.*, s.name AS stream_name FROM logs l LEFT JOIN streams s ON s.id=l.stream_id "
                "ORDER BY l.id DESC LIMIT ?", (limit,))
    return JSONResponse(rows)


async def api_stats(request):
    need_admin(request)
    return JSONResponse({
        "streams": db.one("SELECT COUNT(*) n FROM streams")["n"],
        "running": sum(1 for w in manager.workers.values() if w.status in ("live", "connecting", "reconnecting")),
        "segments": db.one("SELECT COUNT(*) n FROM segments")["n"],
        "segments_24h": db.one("SELECT COUNT(*) n FROM segments WHERE ts>?", (time.time() - 86400,))["n"],
        "users": db.one("SELECT COUNT(*) n FROM users")["n"],
        "db_mb": round(os.path.getsize(os.path.join(DATA_DIR, "transcriber.db")) / 1e6, 1),
    })


# middleware -------------------------------------------------------------------
class GuardMiddleware:
    """JSON errors for /api, and a CSRF guard: state-changing API calls must carry
    X-Requested-With, which browsers won't let another site add cross-origin."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith("/api/") and scope["method"] not in ("GET", "HEAD"):
            headers = dict(scope["headers"])
            if headers.get(b"x-requested-with") != b"fetch":
                await JSONResponse({"error": "Missing request header"}, 403)(scope, receive, send)
                return
        await self.app(scope, receive, send)


async def http_error(request, exc):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": exc.detail}, exc.status_code)
    return PlainTextResponse(exc.detail, exc.status_code)


@contextlib.asynccontextmanager
async def lifespan(app):
    db.log("info", "Stream Transcriber starting")
    await manager.start_all()
    yield
    await manager.stop_all()


routes = [
    Route("/", page_index),
    Route("/login", page_login),
    Route("/admin", page_admin),
    Route("/healthz", health),
    Route("/api/setup", api_setup_status, methods=["GET"]),
    Route("/api/setup", api_setup, methods=["POST"]),
    Route("/api/login", api_login, methods=["POST"]),
    Route("/api/logout", api_logout, methods=["POST"]),
    Route("/api/me", api_me),
    Route("/api/me/password", api_change_password, methods=["POST"]),
    Route("/api/streams", api_streams, methods=["GET", "POST"]),
    Route("/api/streams/{sid:int}", api_stream, methods=["GET", "PATCH", "DELETE"]),
    Route("/api/streams/{sid:int}/segments", api_segments),
    Route("/api/streams/{sid:int}/export", api_export),
    Route("/api/events", api_events),
    Route("/api/admin/users", api_users, methods=["GET", "POST"]),
    Route("/api/admin/users/{uid:int}", api_user, methods=["PATCH", "DELETE"]),
    Route("/api/admin/settings", api_settings, methods=["GET", "PUT"]),
    Route("/api/admin/test-whisper", api_test_whisper, methods=["POST"]),
    Route("/api/admin/logs", api_logs),
    Route("/api/admin/stats", api_stats),
    Mount("/static", StaticFiles(directory=STATIC), name="static"),
]

app = Starlette(
    routes=routes,
    lifespan=lifespan,
    exception_handlers={HTTPException: http_error},
    middleware=[
        Middleware(SessionMiddleware, secret_key=load_secret(DATA_DIR), session_cookie="st_session",
                   max_age=30 * 86400, same_site="lax",
                   https_only=os.environ.get("COOKIE_SECURE", "0") == "1"),
        Middleware(GuardMiddleware),
    ],
)
