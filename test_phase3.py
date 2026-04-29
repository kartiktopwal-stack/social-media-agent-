"""
test_phase3.py
─────────────────────────────────────────────────────────────────────────────
Phase 3 integration test — verifies the clip enhancement pipeline.

Picks the first clip with status='ready' or 'enhanced' from SQLite,
runs enhance_clip() on it, then prints the Gemini scores, hook text,
and confirms the _final.mp4 file exists on disk.

Run:
    python test_phase3.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)


def main() -> None:
    print("=" * 60)
    print("  TEST: Phase 3 — Clip Enhancement Pipeline")
    print("=" * 60)

    # ── 1. Initialize database + ensure columns ───────────────────────
    print("\n[1/4] Initializing database ...")
    from src.core.db import init_database, get_connection

    init_database()
    print("  ✅ Database initialized")

    # ── 2. Find first clip with status='ready' or 'enhanced' ──────────
    print("\n[2/4] Finding a clip to enhance ...")
    conn = get_connection()
    row = conn.execute(
        "SELECT id, clip_path, status, start_sec, end_sec "
        "FROM clips WHERE status IN ('ready', 'enhanced') "
        "ORDER BY id ASC LIMIT 1"
    ).fetchone()
    conn.close()

    if not row:
        print("  ❌ No clips with status='ready' or 'enhanced' found in DB.")
        print("     Run test_phase2.py first to extract clips.")
        sys.exit(1)

    clip_id = row["id"]
    clip_path = row["clip_path"]
    print(f"  Found clip #{clip_id}: {clip_path}")
    print(f"  Range: {row['start_sec']}s – {row['end_sec']}s  Status: {row['status']}")

    # ── 3. Run enhance_clip ───────────────────────────────────────────
    print(f"\n[3/4] Running enhance_clip({clip_id}) ...")
    from clip_enhancer import enhance_clip

    final_path = enhance_clip(clip_id)

    # ── 4. Verify results ─────────────────────────────────────────────
    print(f"\n[4/4] Verifying results ...")

    conn = get_connection()
    enhanced = conn.execute(
        "SELECT id, clip_path, gemini_score, hook_text, final_path, status "
        "FROM clips WHERE id = ?",
        (clip_id,),
    ).fetchone()
    conn.close()

    if not enhanced:
        print("  ❌ Clip row not found after enhancement!?")
        sys.exit(1)

    print(f"\n  ── Results for Clip #{clip_id} ──")
    print(f"  Status:       {enhanced['status']}")
    print(f"  Gemini Score: {enhanced['gemini_score']}")
    print(f"  Hook Text:    {enhanced['hook_text']}")
    print(f"  Final Path:   {enhanced['final_path']}")

    # Check file existence
    final_file = Path(enhanced["final_path"]) if enhanced["final_path"] else None
    # Also check by the returned path
    alt_final = Path(final_path)

    file_exists = (final_file and final_file.exists()) or alt_final.exists()

    if file_exists:
        actual = final_file if (final_file and final_file.exists()) else alt_final
        size_mb = actual.stat().st_size / (1024 * 1024)
        print(f"\n  ✅ Final file exists: {actual.name} ({size_mb:.2f} MB)")
    else:
        print(f"\n  ❌ Final file NOT found: {final_path}")

    # ── Subbed intermediate should be cleaned up ──────────────────────
    base = clip_path.rsplit(".", 1)[0] if clip_path else ""
    subbed = Path(f"{base}_subbed.mp4")
    if subbed.exists():
        print(f"  ⚠️  Intermediate _subbed.mp4 still exists (should have been cleaned)")
    else:
        print(f"  ✅ Intermediate _subbed.mp4 cleaned up")

    # ── Final verdict ─────────────────────────────────────────────────
    print("\n" + "=" * 60)
    if (
        enhanced["status"] == "enhanced"
        and enhanced["gemini_score"] is not None
        and enhanced["hook_text"]
        and file_exists
    ):
        print("  🎉  PHASE 3 — ALL TESTS PASSED")
        print(f"       Gemini score:  {enhanced['gemini_score']}")
        print(f"       Hook text:     {enhanced['hook_text']}")
        print(f"       Final clip:    {enhanced['final_path']}")
    else:
        print("  ⚠️  PHASE 3 — SOME CHECKS FAILED")
        if enhanced["status"] != "enhanced":
            print(f"       Status is '{enhanced['status']}', expected 'enhanced'")
        if enhanced["gemini_score"] is None:
            print("       gemini_score is NULL")
        if not enhanced["hook_text"]:
            print("       hook_text is empty")
        if not file_exists:
            print("       Final MP4 file does not exist on disk")
    print("=" * 60)

    sys.exit(0 if (enhanced["status"] == "enhanced" and file_exists) else 1)


if __name__ == "__main__":
    main()
