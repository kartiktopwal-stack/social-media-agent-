"""
src/core/db.py
─────────────────────────────────────────────────────────────────────────────
Database initialization and session management (SQLite for local dev).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from config.settings import settings
from src.utils.logger import get_logger

logger = get_logger("db")

_DB_PATH: Path | None = None


def _get_db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        db_url = settings.database_url
        if db_url.startswith("sqlite:///"):
            _DB_PATH = Path(db_url.replace("sqlite:///", ""))
        else:
            _DB_PATH = settings.project_root / "data" / "content_empire.db"
    return _DB_PATH


def init_database() -> None:
    """Create SQLite tables if they don't exist."""
    settings.ensure_dirs()
    db_path = _get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info("initializing_database", path=str(db_path))

    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
        logger.info("database_ready")
    except Exception:
        logger.exception("database_init_failed")
        raise
    finally:
        conn.close()


def get_connection() -> sqlite3.Connection:
    """Return a new SQLite connection."""
    db_path = _get_db_path()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


_SCHEMA = """
CREATE TABLE IF NOT EXISTS trends (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    niche       TEXT NOT NULL,
    topic       TEXT NOT NULL,
    source      TEXT NOT NULL,
    virality    REAL DEFAULT 0,
    description TEXT DEFAULT '',
    collected_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS scripts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    trend_id    INTEGER REFERENCES trends(id),
    niche       TEXT NOT NULL,
    title       TEXT NOT NULL,
    hook        TEXT DEFAULT '',
    body        TEXT DEFAULT '',
    cta         TEXT DEFAULT '',
    full_text   TEXT DEFAULT '',
    word_count  INTEGER DEFAULT 0,
    platform    TEXT DEFAULT 'youtube',
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT UNIQUE NOT NULL,
    niche       TEXT NOT NULL,
    status      TEXT DEFAULT 'pending',
    trend_topic TEXT DEFAULT '',
    script_id   INTEGER REFERENCES scripts(id),
    audio_path  TEXT DEFAULT '',
    video_path  TEXT DEFAULT '',
    final_path  TEXT DEFAULT '',
    error       TEXT DEFAULT '',
    started_at  TEXT DEFAULT (datetime('now')),
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS publish_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT REFERENCES jobs(job_id),
    platform    TEXT NOT NULL,
    success     INTEGER DEFAULT 0,
    post_id     TEXT DEFAULT '',
    post_url    TEXT DEFAULT '',
    error       TEXT DEFAULT '',
    published_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS clips (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    url         TEXT NOT NULL,
    niche       TEXT,
    clip_path   TEXT,
    score       REAL,
    start_sec   REAL,
    end_sec     REAL,
    status      TEXT DEFAULT 'pending',
    gemini_score FLOAT,
    hook_text   TEXT,
    final_path  TEXT,
    youtube_id  TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS keyword_rotation_state (
    niche_name    TEXT PRIMARY KEY,
    current_index INTEGER DEFAULT 0,
    last_updated  TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_trends_niche ON trends(niche);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_niche ON jobs(niche);
CREATE INDEX IF NOT EXISTS idx_clips_niche ON clips(niche);
CREATE INDEX IF NOT EXISTS idx_clips_status ON clips(status);
"""


def _ensure_keyword_rotation_table(conn: sqlite3.Connection) -> None:
    """Create the keyword rotation state table when older DBs are in use."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS keyword_rotation_state (
            niche_name    TEXT PRIMARY KEY,
            current_index INTEGER DEFAULT 0,
            last_updated  TEXT DEFAULT (datetime('now'))
        )
        """
    )


def get_keyword_index(niche_name: str) -> int:
    """Return the current keyword rotation index for a niche."""
    conn = get_connection()
    try:
        _ensure_keyword_rotation_table(conn)
        row = conn.execute(
            """
            SELECT current_index
            FROM keyword_rotation_state
            WHERE niche_name = ?
            """,
            (niche_name,),
        ).fetchone()
        return int(row["current_index"]) if row else 0
    finally:
        conn.close()


def set_keyword_index(niche_name: str, index: int) -> None:
    """Persist the next keyword rotation index for a niche."""
    conn = get_connection()
    try:
        _ensure_keyword_rotation_table(conn)
        conn.execute(
            """
            INSERT INTO keyword_rotation_state (niche_name, current_index, last_updated)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(niche_name) DO UPDATE SET
                current_index = excluded.current_index,
                last_updated = datetime('now')
            """,
            (niche_name, index),
        )
        conn.commit()
    finally:
        conn.close()
