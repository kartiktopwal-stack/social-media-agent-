"""
clip_extractor.py
─────────────────────────────────────────────────────────────────────────────
Phase 1 — Multi-source Clip Engine
Extracts viral short-form clips from long-form YouTube video.

Pipeline:
  1. Download video (yt-dlp, 720p)
  2. Transcribe (faster-whisper, base model, local)
  3. Detect scene boundaries (PySceneDetect ContentDetector)
  4. Compute audio energy timeline (pydub RMS)
  5. Merge into per-second semantic timeline
  6. Score sliding windows → rank top clips
  7. Extract clips (ffmpeg subprocess, 9:16 center crop)
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import warnings
from pathlib import Path
from typing import Any

# ─── ffmpeg binary ────────────────────────────────────────────────────────
def _get_ffmpeg() -> str:
    """Return path to the ffmpeg binary (imageio_ffmpeg bundle or env var)."""
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.isfile(exe):
            return exe
    except ImportError:
        pass

    env = os.getenv("FFMPEG_PATH")
    if env and os.path.isfile(env):
        return env

    # Last resort — hope it's on PATH
    return "ffmpeg"


FFMPEG = _get_ffmpeg()


# ═══════════════════════════════════════════════════════════════════════════
# 1. DOWNLOAD
# ═══════════════════════════════════════════════════════════════════════════
def _is_direct_video_url(url: str) -> bool:
    """Check if the URL points directly to a video file (not YouTube/etc)."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    path_lower = parsed.path.lower()
    return any(path_lower.endswith(ext) for ext in (".mp4", ".mkv", ".webm", ".avi", ".mov"))


def _download_direct(url: str, output_dir: str) -> str:
    """Download a video file from a direct URL (e.g. archive.org CDN)."""
    import urllib.request
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / "source_video.mp4"

    # Skip if already cached
    if dest.exists() and dest.stat().st_size > 100_000:
        size_mb = dest.stat().st_size / (1024 * 1024)
        print(f"  ✓ Already cached: {dest} ({size_mb:.1f} MB)")
        return str(dest)

    print(f"  Downloading direct URL ...")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp, open(str(dest), "wb") as f:
        while True:
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)

    if not dest.exists() or dest.stat().st_size < 1000:
        raise RuntimeError(f"Direct download failed or file too small: {url}")

    size_mb = dest.stat().st_size / (1024 * 1024)
    print(f"  ✓ Saved: {dest} ({size_mb:.1f} MB)")
    return str(dest)


def _download_ytdlp(url: str, output_dir: str) -> str:
    """Download a YouTube video at 720p using yt-dlp."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    output_template = str(out / "source_video.%(ext)s")

    cmd = [
        sys.executable, "-m", "yt_dlp",
        url,
        "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best",
        "--merge-output-format", "mp4",
        "-o", output_template,
        "--no-playlist",
        "--force-overwrites",
        "--ffmpeg-location", FFMPEG,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(
                f"yt-dlp failed for URL {url}\n"
                f"stderr: {result.stderr[-500:]}"
            )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"yt-dlp timed out downloading {url}")

    # Find the downloaded file
    mp4_files = sorted(out.glob("source_video.*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not mp4_files:
        raise RuntimeError(f"No video file found after download from {url}")

    video_path = str(mp4_files[0])
    size_mb = mp4_files[0].stat().st_size / (1024 * 1024)
    print(f"  ✓ Saved: {video_path} ({size_mb:.1f} MB)")
    return video_path


def download_video(url: str, output_dir: str = "./clips") -> str:
    """Download a video — supports YouTube (yt-dlp) and direct file URLs.

    Returns the local file path of the downloaded video.
    Raises RuntimeError if the download fails.
    """
    print(f"\n{'='*60}")
    print(f"[1/7] ⬇  Downloading video: {url}")
    print(f"{'='*60}")

    if _is_direct_video_url(url):
        return _download_direct(url, output_dir)
    else:
        return _download_ytdlp(url, output_dir)


# ═══════════════════════════════════════════════════════════════════════════
# 2. TRANSCRIBE
# ═══════════════════════════════════════════════════════════════════════════
def transcribe_video(video_path: str) -> list[dict[str, Any]]:
    """Transcribe video using faster-whisper (base model, local CPU).

    Returns list of word-level dicts: [{word, start, end}, ...]
    """
    print(f"\n{'='*60}")
    print(f"[2/7] 🎙  Transcribing: {Path(video_path).name}")
    print(f"{'='*60}")

    from faster_whisper import WhisperModel

    model = WhisperModel("base", device="cpu", compute_type="int8")
    segments, info = model.transcribe(video_path, word_timestamps=True)

    words: list[dict[str, Any]] = []
    for segment in segments:
        if segment.words:
            for w in segment.words:
                words.append({
                    "word": w.word.strip(),
                    "start": round(w.start, 3),
                    "end": round(w.end, 3),
                })

    print(f"  ✓ Transcribed {len(words)} words")
    print(f"    Language: {info.language} (prob {info.language_probability:.2f})")
    if words:
        duration = words[-1]["end"]
        print(f"    Duration covered: {duration:.1f}s")
    return words


# ═══════════════════════════════════════════════════════════════════════════
# 3. SCENE DETECTION
# ═══════════════════════════════════════════════════════════════════════════
def detect_scenes(video_path: str) -> list[dict[str, float]]:
    """Detect scene boundaries using PySceneDetect ContentDetector.

    Returns list of dicts: [{scene_start_sec, scene_end_sec}, ...]
    """
    print(f"\n{'='*60}")
    print(f"[3/7] 🎬  Detecting scenes: {Path(video_path).name}")
    print(f"{'='*60}")

    from scenedetect import open_video, SceneManager
    from scenedetect.detectors import ContentDetector

    video = open_video(video_path)
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector(threshold=27.0))
    scene_manager.detect_scenes(video, show_progress=False)

    scene_list = scene_manager.get_scene_list()

    scenes: list[dict[str, float]] = []
    for start_time, end_time in scene_list:
        scenes.append({
            "scene_start_sec": round(start_time.get_seconds(), 3),
            "scene_end_sec": round(end_time.get_seconds(), 3),
        })

    print(f"  ✓ Detected {len(scenes)} scenes")
    if scenes:
        print(f"    First: {scenes[0]['scene_start_sec']:.1f}s → {scenes[0]['scene_end_sec']:.1f}s")
        print(f"    Last:  {scenes[-1]['scene_start_sec']:.1f}s → {scenes[-1]['scene_end_sec']:.1f}s")
    return scenes


# ═══════════════════════════════════════════════════════════════════════════
# 4. ENERGY TIMELINE
# ═══════════════════════════════════════════════════════════════════════════
def compute_energy_timeline(video_path: str) -> list[dict[str, float]]:
    """Extract audio from video and compute RMS energy per second.

    Returns list of dicts: [{time_sec, rms}, ...]
    """
    print(f"\n{'='*60}")
    print(f"[4/7] 📊  Computing audio energy: {Path(video_path).name}")
    print(f"{'='*60}")

    # Step 1: Extract audio to WAV using ffmpeg subprocess.
    # We do this instead of pydub.AudioSegment.from_file(video) because
    # pydub calls ffprobe to detect format, but imageio_ffmpeg only ships
    # ffmpeg — not ffprobe — causing WinError 2 on Windows.
    wav_path = str(Path(video_path).with_suffix(".wav"))
    extract_cmd = [
        FFMPEG, "-y",
        "-i", video_path,
        "-vn",                  # drop video
        "-acodec", "pcm_s16le", # 16-bit PCM
        "-ar", "16000",         # 16 kHz (fast, enough for RMS)
        "-ac", "1",             # mono
        wav_path,
    ]
    print("  Extracting audio to WAV ...")
    result = subprocess.run(extract_cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg audio extraction failed:\n{result.stderr[-500:]}"
        )

    # Step 2: Load the WAV with pydub (reads WAV natively — no ffprobe needed)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        from pydub import AudioSegment

    audio = AudioSegment.from_wav(wav_path)
    duration_sec = len(audio) / 1000.0

    energy: list[dict[str, float]] = []
    for sec in range(int(duration_sec)):
        chunk = audio[sec * 1000 : (sec + 1) * 1000]
        rms_val = chunk.rms
        energy.append({
            "time_sec": sec,
            "rms": rms_val,
        })

    # Normalize RMS to 0-1 range
    if energy:
        max_rms = max(e["rms"] for e in energy) or 1
        for e in energy:
            e["rms"] = round(e["rms"] / max_rms, 4)

    # Clean up temp WAV
    try:
        os.remove(wav_path)
    except OSError:
        pass

    print(f"  ✓ Computed energy for {len(energy)} seconds")
    avg_energy = sum(e["rms"] for e in energy) / len(energy) if energy else 0
    print(f"    Average normalized RMS: {avg_energy:.3f}")
    return energy


# ═══════════════════════════════════════════════════════════════════════════
# 5. SEMANTIC TIMELINE
# ═══════════════════════════════════════════════════════════════════════════
def build_semantic_timeline(
    transcription: list[dict],
    scenes: list[dict],
    energy: list[dict],
) -> list[dict[str, Any]]:
    """Merge transcription, scenes, and energy into a per-second timeline.

    Returns list of dicts:
        [{time, word, scene_start, energy_rms}, ...]
    """
    print(f"\n{'='*60}")
    print(f"[5/7] 🔗  Building semantic timeline")
    print(f"{'='*60}")

    # Pre-compute lookup structures
    max_sec = max(
        (e["time_sec"] for e in energy),
        default=0,
    )

    # Energy lookup
    energy_map: dict[int, float] = {e["time_sec"]: e["rms"] for e in energy}

    # Scene boundary set (seconds where a new scene starts)
    scene_starts: set[int] = set()
    for s in scenes:
        scene_starts.add(int(s["scene_start_sec"]))

    # Words per second
    words_per_sec: dict[int, list[str]] = {}
    for w in transcription:
        sec = int(w["start"])
        words_per_sec.setdefault(sec, []).append(w["word"])

    timeline: list[dict[str, Any]] = []
    for sec in range(max_sec + 1):
        word_text = " ".join(words_per_sec.get(sec, []))
        timeline.append({
            "time": sec,
            "word": word_text if word_text else "",
            "scene_start": sec in scene_starts,
            "energy_rms": energy_map.get(sec, 0.0),
        })

    print(f"  ✓ Timeline: {len(timeline)} seconds")
    words_with_text = sum(1 for t in timeline if t["word"])
    print(f"    Seconds with speech: {words_with_text}")
    print(f"    Scene boundaries: {len(scene_starts)}")
    return timeline


# ═══════════════════════════════════════════════════════════════════════════
# 6. SCORE WINDOWS
# ═══════════════════════════════════════════════════════════════════════════
def score_windows(
    timeline: list[dict],
    window_sec: int = 30,
) -> list[dict[str, Any]]:
    """Slide a window across the timeline and score each position.

    Scoring weights:
      - Average energy:           40%
      - Word density / pacing:    30%
      - Scene boundary bonus:     30%

    Returns top 10 windows sorted by score descending.
    """
    print(f"\n{'='*60}")
    print(f"[6/7] 🏆  Scoring windows (window={window_sec}s)")
    print(f"{'='*60}")

    if len(timeline) < window_sec:
        print("  ⚠ Video shorter than window size, using full video as one window")
        window_sec = len(timeline)

    results: list[dict[str, Any]] = []

    for start in range(len(timeline) - window_sec + 1):
        window = timeline[start : start + window_sec]

        # 1) Average energy (0-1)
        avg_energy = sum(t["energy_rms"] for t in window) / window_sec

        # 2) Word density — words per second in the window
        total_words = sum(len(t["word"].split()) for t in window if t["word"])
        word_density = total_words / window_sec
        # Normalize: assume ideal pacing ~2.5 words/sec (conversational)
        # Cap at 1.0 for density score
        density_score = min(word_density / 2.5, 1.0)

        # 3) Scene boundary bonus — more scene changes = more visual dynamism
        scene_count = sum(1 for t in window if t["scene_start"])
        # Normalize: cap at ~5 scenes per window for max bonus
        scene_score = min(scene_count / 5.0, 1.0)

        # Composite
        score = (avg_energy * 0.40) + (density_score * 0.30) + (scene_score * 0.30)

        results.append({
            "start_sec": start,
            "end_sec": start + window_sec,
            "score": round(score, 4),
            "avg_energy": round(avg_energy, 4),
            "word_density": round(word_density, 2),
            "scene_changes": scene_count,
        })

    # Sort by score descending
    results.sort(key=lambda x: x["score"], reverse=True)

    # Deduplicate overlapping windows — keep top non-overlapping
    filtered: list[dict[str, Any]] = []
    for r in results:
        overlaps = False
        for kept in filtered:
            if not (r["end_sec"] <= kept["start_sec"] or r["start_sec"] >= kept["end_sec"]):
                overlaps = True
                break
        if not overlaps:
            filtered.append(r)
        if len(filtered) >= 10:
            break

    print(f"  ✓ Scored {len(results)} windows, kept top {len(filtered)} non-overlapping")
    for i, w in enumerate(filtered[:5]):
        print(
            f"    #{i+1}: {w['start_sec']}s–{w['end_sec']}s  "
            f"score={w['score']:.4f}  "
            f"energy={w['avg_energy']:.3f}  "
            f"wps={w['word_density']:.1f}  "
            f"scenes={w['scene_changes']}"
        )

    return filtered


# ═══════════════════════════════════════════════════════════════════════════
# 7. EXTRACT CLIP
# ═══════════════════════════════════════════════════════════════════════════
def extract_clip(
    video_path: str,
    start_sec: float,
    end_sec: float,
    output_path: str,
) -> str:
    """Cut a clip from the source video, re-encode to 9:16 center crop.

    Uses ffmpeg subprocess for speed (not MoviePy).
    Returns the output file path.
    """
    duration = end_sec - start_sec
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # 9:16 center crop filter:
    # Calculate crop dimensions based on input.
    # For 16:9 → 9:16: take a vertical strip from center.
    # crop=ih*9/16:ih:(iw-ih*9/16)/2:0
    crop_filter = "crop=ih*9/16:ih:(iw-ih*9/16)/2:0"

    cmd = [
        FFMPEG,
        "-y",                          # Overwrite
        "-ss", str(start_sec),         # Seek (before input = fast)
        "-i", video_path,
        "-t", str(duration),
        "-vf", crop_filter,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(out),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg clip extraction failed:\n{result.stderr[-500:]}"
        )

    size_mb = out.stat().st_size / (1024 * 1024)
    print(f"    ✓ Clip saved: {out.name} ({size_mb:.1f} MB, {duration:.0f}s)")
    return str(out)


# ═══════════════════════════════════════════════════════════════════════════
# ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════
def run_extraction(
    youtube_url: str,
    output_dir: str = "./clips",
    window_sec: int = 30,
    top_n_clips: int = 3,
) -> list[str]:
    """Full end-to-end clip extraction pipeline.

    1. Download → 2. Transcribe → 3. Scenes → 4. Energy →
    5. Timeline → 6. Score → 7. Extract top clips

    Returns list of output clip file paths.
    """
    print("\n" + "━" * 60)
    print("  🚀  CLIP EXTRACTOR — Phase 1 Pipeline")
    print("━" * 60)

    # Step 1: Download
    video_path = download_video(youtube_url, output_dir)

    # Step 2: Transcribe
    transcription = transcribe_video(video_path)

    # Step 3: Scene detection
    scenes = detect_scenes(video_path)

    # Step 4: Energy timeline
    energy = compute_energy_timeline(video_path)

    # Step 5: Build semantic timeline
    timeline = build_semantic_timeline(transcription, scenes, energy)

    # Step 6: Score windows
    top_windows = score_windows(timeline, window_sec=window_sec)

    # Step 7: Extract top clips
    print(f"\n{'='*60}")
    print(f"[7/7] ✂  Extracting top {top_n_clips} clips")
    print(f"{'='*60}")

    clip_paths: list[str] = []
    for i, window in enumerate(top_windows[:top_n_clips]):
        clip_name = f"clip_{i+1:03d}.mp4"
        clip_path = str(Path(output_dir) / clip_name)
        try:
            path = extract_clip(
                video_path,
                window["start_sec"],
                window["end_sec"],
                clip_path,
            )
            clip_paths.append(path)
        except RuntimeError as e:
            print(f"    ✗ Failed to extract clip {i+1}: {e}")

    # Print summary
    print(f"\n{'━'*60}")
    print(f"  ✅  DONE — {len(clip_paths)} clips extracted to {output_dir}/")
    print(f"{'━'*60}")

    print("\n  Top 5 Window Scores:")
    print(f"  {'#':<4} {'Start':>6} {'End':>6} {'Score':>8} {'Energy':>8} {'WPS':>6} {'Scenes':>7}")
    print(f"  {'─'*4} {'─'*6} {'─'*6} {'─'*8} {'─'*8} {'─'*6} {'─'*7}")
    for i, w in enumerate(top_windows[:5]):
        print(
            f"  {i+1:<4} {w['start_sec']:>5}s {w['end_sec']:>5}s "
            f"{w['score']:>8.4f} {w['avg_energy']:>8.4f} "
            f"{w['word_density']:>5.1f} {w['scene_changes']:>6}"
        )

    print(f"\n  Clip files:")
    for p in clip_paths:
        print(f"    📎 {p}")

    # Save timeline as JSON for debugging / Phase 2
    timeline_path = Path(output_dir) / "timeline.json"
    with open(timeline_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "source_url": youtube_url,
                "source_video": video_path,
                "timeline": timeline,
                "top_windows": top_windows[:10],
                "clips": clip_paths,
            },
            f,
            indent=2,
        )
    print(f"  📄 Timeline saved: {timeline_path}")

    return clip_paths


# ─── CLI entry point ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Extract viral clips from YouTube video")
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument("--output", "-o", default="./clips", help="Output directory")
    parser.add_argument("--window", "-w", type=int, default=30, help="Window size in seconds")
    parser.add_argument("--clips", "-n", type=int, default=3, help="Number of clips to extract")
    args = parser.parse_args()

    run_extraction(args.url, args.output, args.window, args.clips)
