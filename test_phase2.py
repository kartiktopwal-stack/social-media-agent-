"""
test_phase2.py
─────────────────────────────────────────────────────────────────────────────
Phase 2 integration test — verifies the Celery clip pipeline end-to-end.

Calls process_clip_job directly (synchronous, no Celery worker needed).
Then queries the clips table and confirms MP4 files exist on disk.

Run:
    python test_phase2.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

# ─── Test configuration ──────────────────────────────────────────────────
# Same Big Buck Bunny URL from Phase 1 (already cached in ./clips/)
TEST_URL = "https://archive.org/download/BigBuckBunny_328/BigBuckBunny_512kb.mp4"
TEST_NICHE = "technology"


def main() -> None:
    print("=" * 60)
    print("  TEST: Phase 2 — Celery Clip Pipeline Integration")
    print("=" * 60)

    # ── 1. Initialize the database (creates clips table) ──────────────
    print("\n[1/4] Initializing database ...")
    from src.core.db import init_database

    init_database()
    print("  ✅ Database initialized (clips table ready)")

    # ── 2. Call process_clip_job directly (synchronous) ────────────────
    print(f"\n[2/4] Running process_clip_job('{TEST_URL}', niche='{TEST_NICHE}') ...")
    print("       (Calling task function directly — no Celery worker needed)\n")

    from tasks.clip_tasks import process_clip_job

    result = process_clip_job(TEST_URL, niche=TEST_NICHE)

    print(f"\n  Task result: status={result['status']}")
    if result["status"] == "failed":
        print(f"  Error: {result.get('error', 'unknown')}")
        sys.exit(1)

    clips_from_task = result.get("clips", [])
    print(f"  Clips returned: {len(clips_from_task)}")

    # ── 3. Query the clips table in SQLite ────────────────────────────
    print(f"\n[3/4] Querying 'clips' table in SQLite ...")
    from src.core.db import get_connection

    conn = get_connection()
    cursor = conn.execute(
        "SELECT id, url, niche, clip_path, score, start_sec, end_sec, status, created_at "
        "FROM clips WHERE url = ? AND niche = ? ORDER BY id DESC",
        (TEST_URL, TEST_NICHE),
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print("  ❌ No rows found in clips table!")
        sys.exit(1)

    print(f"  Found {len(rows)} row(s):\n")
    print(f"  {'ID':<5} {'Score':<8} {'Start':>7} {'End':>7} {'Status':<8} {'Path'}")
    print(f"  {'─'*5} {'─'*8} {'─'*7} {'─'*7} {'─'*8} {'─'*40}")
    for row in rows:
        print(
            f"  {row['id']:<5} {row['score']:<8.4f} "
            f"{row['start_sec']:>6.1f}s {row['end_sec']:>6.1f}s "
            f"{row['status']:<8} {row['clip_path']}"
        )

    # ── 4. Verify MP4 files exist on disk ─────────────────────────────
    print(f"\n[4/4] Verifying clip files exist on disk ...")
    all_exist = True
    for row in rows:
        clip_path = Path(row["clip_path"])
        if row["status"] == "ready" and clip_path.exists() and clip_path.stat().st_size > 0:
            size_mb = clip_path.stat().st_size / (1024 * 1024)
            print(f"  ✅ {clip_path.name}: {size_mb:.2f} MB")
        elif row["status"] == "failed":
            print(f"  ⚠️  {row['id']}: status=failed (no file expected)")
        else:
            print(f"  ❌ {clip_path}: missing or empty")
            all_exist = False

    # ── Final verdict ─────────────────────────────────────────────────
    ready_rows = [r for r in rows if r["status"] == "ready"]

    print("\n" + "=" * 60)
    if ready_rows and all_exist:
        print("  🎉  PHASE 2 — ALL TESTS PASSED")
        print(f"       {len(ready_rows)} clips in DB with status='ready'")
        print(f"       All MP4 files verified on disk")
    else:
        print("  ⚠️  PHASE 2 — SOME CHECKS FAILED")
        if not ready_rows:
            print("       No rows with status='ready' in clips table")
        if not all_exist:
            print("       Some MP4 files missing from disk")
    print("=" * 60)

    sys.exit(0 if (ready_rows and all_exist) else 1)


if __name__ == "__main__":
    main()
