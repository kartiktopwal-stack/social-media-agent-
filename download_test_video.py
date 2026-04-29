"""Download a small test video for clip_extractor testing."""
import os
import sys
from pathlib import Path
from urllib.request import urlretrieve, Request
from urllib.request import urlopen

URL = "https://archive.org/download/BigBuckBunny_328/BigBuckBunny_512kb.mp4"
DEST = Path("./clips/source_video.mp4")

def download():
    DEST.parent.mkdir(parents=True, exist_ok=True)
    
    if DEST.exists() and DEST.stat().st_size > 100_000:
        print(f"Already exists: {DEST} ({DEST.stat().st_size / 1024 / 1024:.1f} MB)")
        return
    
    print(f"Downloading: {URL}")
    print(f"Destination: {DEST}")
    
    # Use a proper User-Agent to avoid 403
    import urllib.request
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp, open(str(DEST), "wb") as out:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        chunk_size = 1024 * 256
        while True:
            chunk = resp.read(chunk_size)
            if not chunk:
                break
            out.write(chunk)
            downloaded += len(chunk)
            if total > 0:
                pct = downloaded / total * 100
                print(f"\r  {downloaded / 1024 / 1024:.1f} / {total / 1024 / 1024:.1f} MB ({pct:.0f}%)", end="", flush=True)
    
    print()
    size_mb = DEST.stat().st_size / 1024 / 1024
    print(f"Done: {size_mb:.1f} MB")

if __name__ == "__main__":
    download()
