"""SQLite storage. One connection, guarded by a lock — plenty for a home server."""
import os
import sqlite3
import threading
import time

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "transcriber.db")

DEFAULT_SETTINGS = {
    "whisper_url": os.environ.get("WHISPER_URL", "http://192.168.1.10:9000"),
    "chunk_seconds": "15",          # length of each audio chunk sent to Whisper
    "default_language": "en",       # blank = auto-detect
    "silence_threshold": "120",     # RMS below this is treated as silence and skipped
    "retention_days": "30",         # transcript lines older than this are deleted (0 = keep forever)
    "max_concurrent": "2",          # simultaneous requests to Whisper across all streams
    "vad_filter": "1",              # ask faster-whisper to strip non-speech
    "use_prompt": "1",              # pass the previous line as initial_prompt for continuity
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
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY,
    stream_id INTEGER NOT NULL REFERENCES streams(id) ON DELETE CASCADE,
    ts REAL NOT NULL,
    duration REAL NOT NULL,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_segments_stream_ts ON segments(stream_id, ts);
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

    def prune(self, retention_days):
        now = time.time()
        if retention_days > 0:
            self.x("DELETE FROM segments WHERE ts < ?", (now - retention_days * 86400,))
        self.x("DELETE FROM logs WHERE ts < ?", (now - 14 * 86400,))
