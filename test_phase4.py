"""
test_phase4.py
─────────────────────────────────────────────────────────────────────────────
Phase 4 integration test — verifies the YouTube upload pipeline.

Picks the first clip with status='enhanced' from SQLite,
calls upload_clip() directly, then confirms:
  - A valid youtube_id is returned
  - SQLite status is 'published'
  - youtube_id is stored in the DB

Run:
    python test_phase4.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Fix Windows cp1252 console encoding for Unicode emojis
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv(override=True)


def main() -> None:
    print("=" * 60)
    print("  TEST: Phase 4 — YouTube Shorts Upload")
    print("=" * 60)

    # ── 1. Initialize database ────────────────────────────────────────
    print("\n[1/4] Initializing database ...")
    from src.core.db import init_database, get_connection

    init_database()
    print("  ✅ Database initialized")

    # ── 2. Find first clip with status='enhanced' ─────────────────────
    print("\n[2/4] Finding an enhanced clip ...")
    conn = get_connection()

    # Ensure youtube_id column exists
    try:
        conn.execute("ALTER TABLE clips ADD COLUMN youtube_id TEXT")
        conn.commit()
    except Exception:
        pass

    row = conn.execute(
        "SELECT id, clip_path, final_path, hook_text, niche, status "
        "FROM clips WHERE status = 'enhanced' "
        "ORDER BY id ASC LIMIT 1"
    ).fetchone()
    conn.close()

    if not row:
        print("  ❌ No clips with status='enhanced' found in DB.")
        print("     Run test_phase3.py first to enhance clips.")
        sys.exit(1)

    clip_id = row["id"]
    print(f"  Found clip #{clip_id}")
    print(f"  Final path:  {row['final_path']}")
    print(f"  Hook text:   {row['hook_text']}")
    print(f"  Niche:       {row['niche']}")

    # Verify file exists
    final = Path(row["final_path"]) if row["final_path"] else None
    if not final or not final.exists():
        print(f"  ❌ Final file does not exist: {row['final_path']}")
        sys.exit(1)
    print(f"  ✅ File exists ({final.stat().st_size / (1024*1024):.2f} MB)")

    # ── 3. Upload clip ────────────────────────────────────────────────
    print(f"\n[3/4] Calling upload_clip({clip_id}) ...")
    from clip_publisher import upload_clip

    youtube_id = upload_clip(clip_id)

    if not youtube_id:
        print("\n  ❌ upload_clip returned None — upload failed.")
        print("     Check logs above for the error details.")
        sys.exit(1)

    print(f"\n  ✅ upload_clip returned youtube_id: {youtube_id}")

    # ── 4. Verify database ────────────────────────────────────────────
    print(f"\n[4/4] Verifying SQLite ...")
    conn = get_connection()
    published = conn.execute(
        "SELECT id, status, youtube_id, final_path, hook_text "
        "FROM clips WHERE id = ?",
        (clip_id,),
    ).fetchone()
    conn.close()

    if not published:
        print("  ❌ Clip row not found!?")
        sys.exit(1)

    print(f"  Status:     {published['status']}")
    print(f"  youtube_id: {published['youtube_id']}")

    # ── Final verdict ─────────────────────────────────────────────────
    print("\n" + "=" * 60)
    if (
        published["status"] == "published"
        and published["youtube_id"]
        and published["youtube_id"] == youtube_id
    ):
        print("  🎉  PHASE 4 — ALL TESTS PASSED")
        print(f"       youtube_id:  {youtube_id}")
        print(f"       Find your video at:")
        print(f"       https://studio.youtube.com/video/{youtube_id}/edit")
    else:
        print("  ⚠️  PHASE 4 — SOME CHECKS FAILED")
        if published["status"] != "published":
            print(f"       Status is '{published['status']}', expected 'published'")
        if not published["youtube_id"]:
            print("       youtube_id is NULL in DB")
        if published["youtube_id"] != youtube_id:
            print("       youtube_id mismatch between DB and returned value")
    print("=" * 60)

    sys.exit(
        0 if (published["status"] == "published" and published["youtube_id"]) else 1
    )


if __name__ == "__main__":
    main()
