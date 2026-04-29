"""Debug runner — captures full traceback to file."""
import traceback
import sys

sys.stdout = open("./clips/debug_out.txt", "w", encoding="utf-8")
sys.stderr = sys.stdout

try:
    from clip_extractor import run_extraction
    run_extraction(
        "https://archive.org/download/BigBuckBunny_328/BigBuckBunny_512kb.mp4",
        "./clips", 30, 3
    )
except Exception:
    traceback.print_exc()
finally:
    sys.stdout.close()
