"""SQLite storage. One connection, guarded by a lock — plenty for a home server."""
import os
import re
import shutil
import sqlite3
import threading
import time

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "transcriber.db")
AUDIO_DIR = os.path.join(DATA_DIR, "audio")

DEFAULT_SETTINGS = {
    "whisper_url": os.environ.get("WHISPER_URL", "http://192.168.1.10:9000"),
    "chunk_seconds": "15",          # length of each audio chunk sent to Whisper
    "default_language": "en",       # blank = auto-detect
    "silence_threshold": "120",     # RMS below this is treated as silence and skipped
    "retention_days": "30",         # transcript lines older than this are deleted (0 = keep forever)
    "max_concurrent": "2",          # simultaneous requests to Whisper across all streams
    "vad_filter": "1",              # ask faster-whisper to strip non-speech
    "use_prompt": "1",              # pass the previous line as initial_prompt for continuity
    "record_audio": "1",            # keep a recording of every stream so lines can be played back
    "audio_bitrate": "96",          # kbps, MP3
    "audio_retention_days": "7",    # recordings older than this are deleted (0 = keep forever)
    "video_thumbs": "1",            # streams with video: save a thumbnail every few seconds for the player timeline
    # Sign in with Microsoft (Entra ID / Azure AD)
    "sso_enabled": "0",
    "sso_tenant_id": "",            # Directory (tenant) ID, or a verified domain like contoso.com
    "sso_client_id": "",            # Application (client) ID of the app registration
    "sso_client_secret": "",        # client secret value; never sent back to the browser
    "sso_allowed_domains": "",      # e.g. "contoso.com, fabrikam.com"; blank = anyone in the tenant
    "sso_auto_create": "1",         # first Microsoft sign-in creates a (non-admin) user
    "sso_button_label": "Sign in with Microsoft",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL COLLATE NOCASE,
    pw_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS streams (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_by TEXT,
    created REAL NOT NULL,
    position INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY,
    stream_id INTEGER NOT NULL REFERENCES streams(id) ON DELETE CASCADE,
    ts REAL NOT NULL,
    duration REAL NOT NULL,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_segments_stream_ts ON segments(stream_id, ts);
-- One row per continuous recording ("take"): a new one starts each time ffmpeg (re)connects.
-- Audio lives in AUDIO_DIR/<stream_id>/<id>/000000.mp3, 000001.mp3 … each seg_seconds long.
CREATE TABLE IF NOT EXISTS recordings (
    id INTEGER PRIMARY KEY,
    stream_id INTEGER NOT NULL REFERENCES streams(id) ON DELETE CASCADE,
    started REAL NOT NULL,
    length REAL NOT NULL DEFAULT 0,
    seg_seconds INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_recordings_stream ON recordings(stream_id, started);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    level TEXT NOT NULL,
    stream_id INTEGER,
    message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs(ts);
"""


class DB:
    def __init__(self, path=DB_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.executescript(SCHEMA)
            cols = {r[1] for r in self.conn.execute("PRAGMA table_info(segments)")}
            if "rec_id" not in cols:  # upgrade from the first version
                self.conn.execute("ALTER TABLE segments ADD COLUMN rec_id INTEGER")
                self.conn.execute("ALTER TABLE segments ADD COLUMN rec_offset REAL")
            rcols = {r[1] for r in self.conn.execute("PRAGMA table_info(recordings)")}
            if "thumb_seconds" not in rcols:  # upgrade: video thumbnails (0 = this take has none)
                self.conn.execute("ALTER TABLE recordings ADD COLUMN thumb_seconds INTEGER NOT NULL DEFAULT 0")
            ucols = {r[1] for r in self.conn.execute("PRAGMA table_info(users)")}
            if "sso_oid" not in ucols:  # upgrade: the Microsoft account (Entra object ID) linked to this user
                self.conn.execute("ALTER TABLE users ADD COLUMN sso_oid TEXT")
            scols = {r[1] for r in self.conn.execute("PRAGMA table_info(streams)")}
            if "category" not in scols:  # upgrade: sidebar groups ('' = not sorted yet, 'video' or 'audio')
                self.conn.execute("ALTER TABLE streams ADD COLUMN category TEXT NOT NULL DEFAULT ''")
            if "position" not in scols:  # upgrade: keep the old alphabetical order as the starting order
                self.conn.execute("ALTER TABLE streams ADD COLUMN position INTEGER NOT NULL DEFAULT 0")
                ids = [r[0] for r in self.conn.execute("SELECT id FROM streams ORDER BY name COLLATE NOCASE")]
                for i, sid in enumerate(ids):
                    self.conn.execute("UPDATE streams SET position=? WHERE id=?", (i, sid))
            for k, v in DEFAULT_SETTINGS.items():
                self.conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
            self.conn.commit()

    def q(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def x(self, sql, args=()):
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur.lastrowid

    # settings -------------------------------------------------------------
    def settings(self):
        return {r["key"]: r["value"] for r in self.q("SELECT key, value FROM settings")}

    def setting(self, key, cast=str):
        row = self.one("SELECT value FROM settings WHERE key=?", (key,))
        val = row["value"] if row else DEFAULT_SETTINGS.get(key, "")
        try:
            return cast(val)
        except (TypeError, ValueError):
            return cast(DEFAULT_SETTINGS[key])

    def set_setting(self, key, value):
        self.x("INSERT INTO settings(key, value) VALUES (?, ?) "
               "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))

    # logs -----------------------------------------------------------------
    def log(self, level, message, stream_id=None):
        self.x("INSERT INTO logs(ts, level, stream_id, message) VALUES (?, ?, ?, ?)",
               (time.time(), level, stream_id, message[:2000]))
        print(f"[{level}] {'#' + str(stream_id) + ' ' if stream_id else ''}{message}", flush=True)

    def prune(self, retention_days, audio_days=0, active_recs=()):
        now = time.time()
        if retention_days > 0:
            self.x("DELETE FROM segments WHERE ts < ?", (now - retention_days * 86400,))
        self.x("DELETE FROM logs WHERE ts < ?", (now - 14 * 86400,))
        if audio_days > 0:
            self.prune_audio(now - audio_days * 86400, set(active_recs))

    def prune_audio(self, cutoff, active=()):
        """Delete audio recorded before cutoff; drop recordings with nothing left.
        Returns (files deleted, bytes freed)."""
        files = freed = 0

        def remove(path):
            nonlocal files, freed
            try:
                size = os.path.getsize(path)
                os.remove(path)
            except OSError:
                return
            files += 1
            freed += size

        for rec in self.q("SELECT * FROM recordings WHERE started < ?", (cutoff,)):
            folder = rec_dir(rec)
            whole = rec["started"] + rec["length"] < cutoff and rec["id"] not in active
            # a file is old once its last second is before the cutoff
            n = int((cutoff - rec["started"]) // rec["seg_seconds"])
            try:
                names = sorted(f for f in os.listdir(folder) if f.endswith(".mp3"))
            except FileNotFoundError:
                names = []
            for name in names:
                if whole or int(name[:-4]) < n:
                    remove(os.path.join(folder, name))
            if rec.get("thumb_seconds") and not whole:
                # thumbnail k shows the moment k * thumb_seconds into the take
                k_cut = int((cutoff - rec["started"]) // rec["thumb_seconds"])
                tdir = os.path.join(folder, "thumbs")
                try:
                    thumbs = [f for f in os.listdir(tdir) if f.endswith(".jpg")]
                except FileNotFoundError:
                    thumbs = []
                for name in thumbs:
                    if int(name[:-4]) < k_cut:
                        remove(os.path.join(tdir, name))
            if whole:
                shutil.rmtree(folder, ignore_errors=True)
                self.x("DELETE FROM recordings WHERE id=?", (rec["id"],))
        return files, freed

    def delete_stream_audio(self, stream_id):
        self.x("DELETE FROM recordings WHERE stream_id=?", (stream_id,))
        shutil.rmtree(os.path.join(AUDIO_DIR, str(int(stream_id))), ignore_errors=True)


def data_storage_status(data_dir=None, mountinfo="/proc/self/mountinfo"):
    """Is the data folder stored somewhere that survives a container update?

    Returns (ok, message). Settings, users, streams and recordings all live in DATA_DIR,
    so it must be mapped to a folder on the host (e.g. /mnt/user/appdata/transcriber-2000).
    Docker otherwise gives it a throwaway volume that Unraid discards on every update."""
    data_dir = os.path.realpath(data_dir or DATA_DIR)
    try:
        with open(mountinfo) as f:
            mounts = [line.split() for line in f]
    except OSError:
        return True, ""  # not Linux / can't tell — don't nag
    if not os.path.exists("/.dockerenv"):
        return True, ""  # running outside Docker (development)
    best = None
    for m in mounts:
        point = m[4].replace("\\040", " ")
        if data_dir == point or data_dir.startswith(point.rstrip("/") + "/"):
            if best is None or len(point) > len(best[4]):
                best = m
    hint = ("Your settings, users, streams, transcripts and recordings will be lost the next time the "
            "container is updated. In Unraid, edit the container and add a Path: container path /data, "
            "host path /mnt/user/appdata/transcriber-2000.")
    if best is None or best[4] == "/":
        return False, "The /data folder isn't mapped to your server. " + hint
    if re.search(r"volumes/[0-9a-f]{64}/_data", best[3]):
        return False, "/data is in a temporary Docker volume, not a folder on your server. " + hint
    return True, ""


def rec_dir(rec):
    return os.path.join(AUDIO_DIR, str(int(rec["stream_id"])), str(int(rec["id"])))
