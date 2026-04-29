"""
db/init_clips_table.py
─────────────────────────────────────────────────────────────────────────────
Standalone migration script — creates the `clips` table in the existing
SQLite database used by the project.

Run:
    python db/init_clips_table.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root is on sys.path so imports work
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from dotenv import load_dotenv

load_dotenv(override=True)

from src.core.db import get_connection

_CLIPS_SCHEMA = """
CREATE TABLE IF NOT EXISTS clips (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    url         TEXT NOT NULL,
    niche       TEXT,
    clip_path   TEXT,
    score       REAL,
    start_sec   REAL,
    end_sec     REAL,
    status      TEXT DEFAULT 'pending',
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_clips_niche ON clips(niche);
CREATE INDEX IF NOT EXISTS idx_clips_status ON clips(status);
"""


def migrate() -> None:
    """Create the clips table and add Phase 3 columns (idempotent)."""
    conn = get_connection()
    try:
        conn.executescript(_CLIPS_SCHEMA)
        conn.commit()
        print("✅  clips table ready")

        # Phase 3 columns — SQLite doesn't support IF NOT EXISTS on ALTER,
        # so we try/except each one and ignore "duplicate column" errors.
        for col_def in (
            "gemini_score FLOAT",
            "hook_text TEXT",
            "final_path TEXT",
            "youtube_id TEXT",
        ):
            try:
                conn.execute(f"ALTER TABLE clips ADD COLUMN {col_def}")
                conn.commit()
                print(f"    ✅  Added column: {col_def.split()[0]}")
            except Exception:
                # Column already exists
                print(f"    ✓  Column already exists: {col_def.split()[0]}")

        # Verify
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='clips'"
        )
        if cursor.fetchone():
            print("    Verified: 'clips' table exists in the database.")
        else:
            print("    ⚠️  Table creation may have failed — not found in sqlite_master.")
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
