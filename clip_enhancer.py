"""
clip_enhancer.py
─────────────────────────────────────────────────────────────────────────────
Phase 3 — Clip Enhancement Pipeline

Functions:
    score_clip_with_gemini   — AI-rate a transcript for virality (via Groq)
    generate_hook_text       — Generate a scroll-stopping hook title
    burn_subtitles           — Burn word-by-word subtitles with ffmpeg drawtext
    add_hook_overlay         — Burn hook text onto the first 3 seconds
    enhance_clip             — Orchestrate all enhancements for a clip_id
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

import imageio_ffmpeg

logger = logging.getLogger("clip_enhancer")

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

# ─── Default scores (used on any AI failure) ──────────────────────────────
_DEFAULT_SCORES: dict[str, Any] = {
    "quotability": 5,
    "hook_strength": 5,
    "self_contained": 5,
    "emotional_intensity": 5,
    "overall_viral_score": 5.0,
}


# ═══════════════════════════════════════════════════════════════════════════
# AI HELPERS  (uses Groq — the project's configured LLM backend)
# ═══════════════════════════════════════════════════════════════════════════

def _get_ai_client():
    """Return a Groq client using the project's established pattern."""
    from groq import Groq

    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing GROQ_API_KEY")
    return Groq(api_key=api_key)


def _ai_chat(prompt: str) -> str:
    """Send a single-message chat and return the text response."""
    client = _get_ai_client()
    response = client.chat.completions.create(
        model=os.getenv("AI_MODEL", "llama-3.3-70b-versatile"),
        messages=[{"role": "user", "content": prompt}],
    )
    return (response.choices[0].message.content or "").strip()


# ═══════════════════════════════════════════════════════════════════════════
# 1. SCORE CLIP
# ═══════════════════════════════════════════════════════════════════════════

def score_clip_with_gemini(
    clip_path: str,
    transcript_segment: str,
) -> dict[str, Any]:
    """Rate a clip's transcript for viral qualities.

    Returns dict with keys:
        quotability, hook_strength, self_contained,
        emotional_intensity, overall_viral_score
    On any error, returns safe defaults (all 5s).
    """
    if not transcript_segment or not transcript_segment.strip():
        logger.warning("Empty transcript — returning default scores")
        return dict(_DEFAULT_SCORES)

    prompt = (
        "Rate this video clip transcript on a scale of 1-10 for each of "
        "these qualities, respond ONLY as JSON with no markdown: "
        '{"quotability": int, "hook_strength": int, "self_contained": int, '
        '"emotional_intensity": int, "overall_viral_score": float}. '
        f"Transcript: {transcript_segment}"
    )

    try:
        raw = _ai_chat(prompt)
        # Strip markdown fences if the model wraps them anyway
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
        scores = json.loads(raw)

        # Validate keys
        for key in _DEFAULT_SCORES:
            if key not in scores:
                scores[key] = _DEFAULT_SCORES[key]
        return scores
    except Exception as exc:
        logger.error("AI scoring failed — using defaults: %s", exc)
        return dict(_DEFAULT_SCORES)


# ═══════════════════════════════════════════════════════════════════════════
# 2. GENERATE HOOK TEXT
# ═══════════════════════════════════════════════════════════════════════════

def generate_hook_text(transcript_segment: str) -> str:
    """Generate a 5-7 word hook title for the clip.

    Fallback: first 6 words of the transcript + '...'
    """
    fallback = " ".join(transcript_segment.split()[:6]) + "..."

    if not transcript_segment or not transcript_segment.strip():
        return fallback

    prompt = (
        "Write a 5-7 word hook title for this video clip that would stop "
        "someone scrolling. Be direct and intriguing. Return ONLY the "
        f"hook text, nothing else. Transcript: {transcript_segment}"
    )

    try:
        hook = _ai_chat(prompt)
        # Strip quotes the model may wrap it in
        hook = hook.strip('"\'').strip()
        if not hook:
            return fallback
        return hook
    except Exception as exc:
        logger.error("Hook generation failed — using fallback: %s", exc)
        return fallback


# ═══════════════════════════════════════════════════════════════════════════
# 3. BURN SUBTITLES
# ═══════════════════════════════════════════════════════════════════════════

def _escape_drawtext(text: str) -> str:
    """Escape special characters for ffmpeg drawtext filter."""
    # Must escape: \ ' : %
    text = text.replace("\\", "\\\\\\\\")
    text = text.replace("'", "'\\\\\\''")
    text = text.replace(":", "\\:")
    text = text.replace("%", "%%")
    return text


def burn_subtitles(
    input_path: str,
    output_path: str,
    word_timestamps: list[dict[str, Any]],
) -> None:
    """Burn word-by-word subtitles onto the video using ffmpeg drawtext.

    word_timestamps: list of {word, start, end} dicts.
    Style: white bold, font size 20, black outline, centred, 75% down.
    """
    if not word_timestamps:
        logger.warning("No word timestamps — copying input as-is")
        import shutil
        shutil.copy2(input_path, output_path)
        return

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Build a chain of drawtext filters, one per word
    filters: list[str] = []
    for wt in word_timestamps:
        word = _escape_drawtext(wt["word"])
        start = float(wt["start"])
        end = float(wt["end"])
        f = (
            f"drawtext=text='{word}'"
            f":fontsize=20"
            f":fontcolor=white"
            f":borderw=2"
            f":bordercolor=black"
            f":x=(w-text_w)/2"
            f":y=h*0.75"
            f":enable='between(t,{start:.3f},{end:.3f})'"
        )
        filters.append(f)

    # Combine all filters with comma separator
    filter_chain = ",".join(filters)

    cmd = [
        FFMPEG, "-y",
        "-i", input_path,
        "-vf", filter_chain,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg subtitle burn failed:\n{result.stderr[-500:]}"
        )
    logger.info("Subtitles burned: %s", output_path)


# ═══════════════════════════════════════════════════════════════════════════
# 4. ADD HOOK OVERLAY
# ═══════════════════════════════════════════════════════════════════════════

def add_hook_overlay(
    input_path: str,
    output_path: str,
    hook_text: str,
) -> None:
    """Burn the hook text onto the first 3 seconds of the video.

    Large text (font size 28), white, bold, centred horizontally, 20% from
    top, with a semi-transparent black box behind it for readability.
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    escaped = _escape_drawtext(hook_text)

    filter_str = (
        f"drawtext=text='{escaped}'"
        f":fontsize=28"
        f":fontcolor=white"
        f":borderw=2"
        f":bordercolor=black"
        f":box=1"
        f":boxcolor=black@0.5"
        f":boxborderw=8"
        f":x=(w-text_w)/2"
        f":y=h*0.20"
        f":enable='between(t,0,3)'"
    )

    cmd = [
        FFMPEG, "-y",
        "-i", input_path,
        "-vf", filter_str,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg hook overlay failed:\n{result.stderr[-500:]}"
        )
    logger.info("Hook overlay added: %s", output_path)


# ═══════════════════════════════════════════════════════════════════════════
# 5. ENHANCE CLIP  (orchestrator)
# ═══════════════════════════════════════════════════════════════════════════

def _load_word_timestamps_for_clip(
    timeline_dir: str,
    start_sec: float,
    end_sec: float,
) -> tuple[str, list[dict[str, Any]]]:
    """Load word timestamps from timeline.json that fall within the clip range.

    The timeline.json stores per-second data with a "word" key.
    We also look for the full word-level data from the transcription
    stored alongside the clips.

    Returns (transcript_text, word_timestamps_adjusted).
    Word timestamps have their times adjusted to be relative to the clip start.
    """
    timeline_path = Path(timeline_dir) / "timeline.json"
    if not timeline_path.exists():
        return "", []

    with open(timeline_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Build transcript text from per-second timeline data
    timeline = data.get("timeline", [])
    words_in_range: list[str] = []
    word_timestamps: list[dict[str, Any]] = []

    for entry in timeline:
        t = entry.get("time", 0)
        if start_sec <= t < end_sec and entry.get("word"):
            words_in_range.append(entry["word"])
            # Create a pseudo word timestamp (1 second duration per entry)
            adjusted_start = t - start_sec
            word_timestamps.append({
                "word": entry["word"],
                "start": round(adjusted_start, 3),
                "end": round(adjusted_start + 1.0, 3),
            })

    transcript = " ".join(words_in_range)
    return transcript, word_timestamps


def enhance_clip(clip_id: int) -> str:
    """Full enhancement pipeline for a single clip.

    1. Pull clip row from SQLite
    2. Load transcript / word timestamps from timeline.json
    3. Score with AI → save to DB
    4. Generate hook text → save to DB
    5. Burn subtitles → _subbed.mp4
    6. Add hook overlay → _final.mp4
    7. Clean up _subbed.mp4 intermediate
    8. Update DB status → 'enhanced', store final_path

    Returns the path to the final enhanced clip.
    """
    from dotenv import load_dotenv
    load_dotenv(override=True)

    from src.core.db import get_connection

    # ── 1. Pull clip from DB ──────────────────────────────────────────
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM clips WHERE id = ?", (clip_id,)
    ).fetchone()
    if not row:
        conn.close()
        raise ValueError(f"No clip found with id={clip_id}")

    clip_path = row["clip_path"]
    start_sec = row["start_sec"]
    end_sec = row["end_sec"]

    # Determine the directory where timeline.json lives
    clip_dir = str(Path(clip_path).parent)

    logger.info(
        "Enhancing clip #%d  %s  (%.1fs–%.1fs)",
        clip_id, Path(clip_path).name, start_sec, end_sec,
    )

    # ── 2. Load transcript + word timestamps from timeline.json ───────
    transcript, word_timestamps = _load_word_timestamps_for_clip(
        clip_dir, start_sec, end_sec,
    )
    has_timeline = bool(transcript)

    if not has_timeline:
        logger.warning(
            "No timeline.json or no words for clip #%d — "
            "skipping subtitle burn", clip_id,
        )

    # ── 3. Score with AI ──────────────────────────────────────────────
    print(f"  [3a] Scoring clip #{clip_id} with AI ...")
    scores = score_clip_with_gemini(clip_path, transcript)
    overall_score = scores.get("overall_viral_score", 5.0)
    print(f"       Scores: {json.dumps(scores, indent=2)}")

    # ── 4. Generate hook text ─────────────────────────────────────────
    print(f"  [3b] Generating hook text ...")
    hook = generate_hook_text(transcript)
    print(f"       Hook: {hook}")

    # ── Save AI results to DB ─────────────────────────────────────────
    _ensure_enhanced_columns(conn)
    conn.execute(
        "UPDATE clips SET gemini_score = ?, hook_text = ? WHERE id = ?",
        (overall_score, hook, clip_id),
    )
    conn.commit()

    # ── 5. Burn subtitles (if timeline available) ─────────────────────
    base = clip_path.rsplit(".", 1)[0]
    subbed_path = f"{base}_subbed.mp4"
    final_path = f"{base}_final.mp4"

    if has_timeline and word_timestamps:
        print(f"  [3c] Burning subtitles → {Path(subbed_path).name} ...")
        burn_subtitles(clip_path, subbed_path, word_timestamps)
        hook_input = subbed_path
    else:
        # No subtitles — feed original directly to hook overlay
        hook_input = clip_path

    # ── 6. Add hook overlay ───────────────────────────────────────────
    print(f"  [3d] Adding hook overlay → {Path(final_path).name} ...")
    add_hook_overlay(hook_input, final_path, hook)

    # ── 7. Clean up intermediate _subbed.mp4 ──────────────────────────
    if Path(subbed_path).exists() and subbed_path != clip_path:
        try:
            os.remove(subbed_path)
            logger.info("Cleaned up intermediate: %s", subbed_path)
        except OSError:
            pass

    # ── 8. Update DB → enhanced ───────────────────────────────────────
    conn.execute(
        "UPDATE clips SET status = 'enhanced', final_path = ? WHERE id = ?",
        (str(Path(final_path).resolve()), clip_id),
    )
    conn.commit()
    conn.close()

    print(f"  ✅ Clip #{clip_id} enhanced → {final_path}")
    return final_path


# ─── DB column migration helper ──────────────────────────────────────────

def _ensure_enhanced_columns(conn) -> None:
    """Add Phase 3 columns to clips table if they don't exist.

    SQLite doesn't support IF NOT EXISTS on ALTER TABLE,
    so we try/except each ALTER and ignore 'duplicate column' errors.
    """
    for col_def in (
        "gemini_score FLOAT",
        "hook_text TEXT",
        "final_path TEXT",
    ):
        try:
            conn.execute(f"ALTER TABLE clips ADD COLUMN {col_def}")
            conn.commit()
        except Exception:
            # Column already exists — that's fine
            pass
