"""
test_extractor.py
─────────────────────────────────────────────────────────────────────────────
Smoke test for clip_extractor.py (Phase 1).

Uses a short Creative Commons YouTube video to validate the full pipeline:
  download → transcribe → scene detect → energy → timeline → score → extract

Run:
    python test_extractor.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ─── Test configuration ──────────────────────────────────────────────────
# Big Buck Bunny — Blender Foundation, Creative Commons Attribution 3.0.
# Direct MP4 link from archive.org (confirmed working).
TEST_URL = "https://archive.org/download/BigBuckBunny_328/BigBuckBunny_512kb.mp4"
OUTPUT_DIR = "./clips"
EXPECTED_CLIPS = 3


def main() -> None:
    print("=" * 60)
    print("  TEST: clip_extractor.py — Full Pipeline Smoke Test")
    print("=" * 60)

    # Clean previous test output
    out = Path(OUTPUT_DIR)
    if out.exists():
        for f in out.glob("clip_*.mp4"):
            f.unlink()
            print(f"  🗑  Cleaned: {f.name}")

    # Import and run
    from clip_extractor import run_extraction

    print(f"\n  URL: {TEST_URL}")
    print(f"  Output: {OUTPUT_DIR}")
    print(f"  Expected clips: {EXPECTED_CLIPS}\n")

    try:
        clip_paths = run_extraction(
            youtube_url=TEST_URL,
            output_dir=OUTPUT_DIR,
            window_sec=30,
            top_n_clips=EXPECTED_CLIPS,
        )
    except Exception as e:
        print(f"\n  ❌ Pipeline FAILED: {e}")
        sys.exit(1)

    # ─── Validate results ─────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  VALIDATION")
    print("=" * 60)

    passed = True

    # Check clip count
    if len(clip_paths) >= EXPECTED_CLIPS:
        print(f"  ✅ Clip count: {len(clip_paths)} (expected ≥ {EXPECTED_CLIPS})")
    else:
        print(f"  ❌ Clip count: {len(clip_paths)} (expected ≥ {EXPECTED_CLIPS})")
        passed = False

    # Check each clip file exists and has non-zero size
    for i, path in enumerate(clip_paths):
        p = Path(path)
        if p.exists() and p.stat().st_size > 0:
            size_mb = p.stat().st_size / (1024 * 1024)
            print(f"  ✅ {p.name}: {size_mb:.2f} MB")
        else:
            print(f"  ❌ {p.name}: missing or empty")
            passed = False

    # Check timeline.json was saved
    timeline_path = out / "timeline.json"
    if timeline_path.exists():
        import json
        with open(timeline_path, "r") as f:
            data = json.load(f)
        print(f"  ✅ timeline.json: {len(data.get('timeline', []))} seconds")
        top_windows = data.get("top_windows", [])
        if top_windows:
            print(f"\n  Top 5 Scored Windows:")
            print(f"  {'#':<4} {'Start':>8} {'End':>8} {'Score':>8}")
            print(f"  {'─'*4} {'─'*8} {'─'*8} {'─'*8}")
            for i, w in enumerate(top_windows[:5]):
                print(f"  {i+1:<4} {w['start_sec']:>7}s {w['end_sec']:>7}s {w['score']:>8.4f}")
    else:
        print(f"  ❌ timeline.json: not found")
        passed = False

    # Final verdict
    print("\n" + "=" * 60)
    if passed:
        print("  🎉  ALL TESTS PASSED")
    else:
        print("  ⚠️  SOME CHECKS FAILED — see above")
    print("=" * 60)

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
