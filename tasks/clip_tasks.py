"""
tasks/clip_tasks.py
─────────────────────────────────────────────────────────────────────────────
Celery tasks for the clip extraction pipeline (Phase 2).

Tasks:
    process_clip_job  — download + extract clips, save metadata to DB
    discover_and_queue — find trending YouTube URLs, queue clip jobs
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

from celery_app import app
from src.core.db import get_connection, init_database
from src.utils.logger import get_logger

logger = logging.getLogger("clip_tasks")
structured_logger = get_logger("clip_tasks")

DEFAULT_MIN_VIRAL_SCORE = 4.0


# ─── TASK 1: Process a single YouTube URL ─────────────────────────────────


@app.task(bind=True, name="tasks.process_clip_job", max_retries=1)
def process_clip_job(self, youtube_url: str, niche: str = "general") -> dict:
    """Download a YouTube video, extract viral clips, and save metadata to DB.

    Returns dict with status and list of clip records inserted.
    """
    logger.info("process_clip_job START — url=%s niche=%s", youtube_url, niche)

    output_dir = f"./clips/{niche}"
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Ensure the clips table exists
    _ensure_clips_table()

    try:
        # ── 1. Run the extraction pipeline ────────────────────────────
        logger.info("Running clip extraction pipeline ...")
        from clip_extractor import run_extraction

        clip_paths = run_extraction(youtube_url, output_dir=output_dir)
        logger.info("Extraction complete — %d clips produced", len(clip_paths))

        # ── 2. Load scored window data from timeline.json ─────────────
        timeline_path = Path(output_dir) / "timeline.json"
        windows: list[dict] = []
        if timeline_path.exists():
            with open(timeline_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            windows = data.get("top_windows", [])

        # ── 3. Insert each clip into the clips table ──────────────────
        conn = get_connection()
        inserted: list[dict] = []
        try:
            for i, clip_path in enumerate(clip_paths):
                window = windows[i] if i < len(windows) else {}
                score = window.get("score", 0.0)
                start_sec = window.get("start_sec", 0.0)
                end_sec = window.get("end_sec", 0.0)

                conn.execute(
                    """
                    INSERT INTO clips
                        (url, niche, clip_path, score, start_sec, end_sec, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        youtube_url,
                        niche,
                        str(Path(clip_path).resolve()),
                        score,
                        start_sec,
                        end_sec,
                        "ready",
                    ),
                )
                inserted.append(
                    {
                        "clip_path": str(Path(clip_path).resolve()),
                        "score": score,
                        "start_sec": start_sec,
                        "end_sec": end_sec,
                        "status": "ready",
                    }
                )
                logger.info(
                    "  Inserted clip #%d — score=%.4f  %ss–%ss  %s",
                    i + 1,
                    score,
                    start_sec,
                    end_sec,
                    clip_path,
                )

            conn.commit()
        finally:
            conn.close()

        logger.info(
            "process_clip_job — %d clips saved to DB, starting enhancement ...",
            len(inserted),
        )

        # ── 3. Enhance each clip (AI scoring + subtitles + hook) ──────
        from clip_enhancer import enhance_clip

        min_viral_score = _get_min_viral_score()
        for clip_rec in inserted:
            # Retrieve the clip_id we just inserted
            conn = get_connection()
            cursor = conn.execute(
                "SELECT id FROM clips WHERE clip_path = ? ORDER BY id DESC LIMIT 1",
                (clip_rec["clip_path"],),
            )
            row = cursor.fetchone()
            conn.close()

            if row:
                clip_id = row["id"]
                try:
                    final = enhance_clip(clip_id)
                    if not _apply_viral_score_gate(clip_id, min_viral_score):
                        clip_rec["status"] = "skipped_low_score"
                        continue
                    clip_rec["status"] = "enhanced"
                    clip_rec["final_path"] = final
                    logger.info(
                        "  Enhanced clip #%d → %s", clip_id, final,
                    )
                except Exception as enh_err:
                    logger.error(
                        "  Enhancement failed for clip #%d: %s",
                        clip_id, enh_err,
                    )
                    # Clip stays at 'ready' — not fatal to the pipeline

        logger.info(
            "process_clip_job DONE — %d clips processed", len(inserted),
        )
        return {"status": "enhanced", "clips": inserted}

    except Exception as exc:
        # Record failure in DB
        logger.error("process_clip_job FAILED — %s", exc, exc_info=True)
        try:
            conn = get_connection()
            conn.execute(
                """
                INSERT INTO clips (url, niche, clip_path, score, start_sec, end_sec, status)
                VALUES (?, ?, '', 0, 0, 0, 'failed')
                """,
                (youtube_url, niche),
            )
            conn.commit()
            conn.close()
        except Exception as db_err:
            logger.error("Failed to record failure in DB: %s", db_err)

        return {"status": "failed", "error": str(exc)}


# ─── TASK 2: Discover trending URLs and queue clip jobs ───────────────────


@app.task(name="tasks.discover_and_queue")
def discover_and_queue(niche: str) -> dict:
    """Query YouTube Trending API for a niche and queue clip extraction jobs.

    Limits to max 5 URLs per niche per run.
    Returns dict with queued URL count.
    """
    logger.info("discover_and_queue START — niche=%s", niche)

    from config.settings import settings
    from src.trend_engine.collector import YouTubeTrendCollector
    from src.utils.models import NicheConfig

    # Load niche config from niches.yaml
    from src.orchestrator.pipeline import load_niches

    all_niches = load_niches()
    niche_cfg = all_niches.get(niche)

    if not niche_cfg:
        # Fallback: build a minimal NicheConfig
        niche_cfg = NicheConfig(
            name=niche,
            display_name=niche.title(),
            description=f"Auto-generated config for {niche}",
            keywords=[niche],
        )

    # Collect trending YouTube URLs
    collector = YouTubeTrendCollector()
    try:
        raw_trends = collector.collect(niche_cfg)
    finally:
        collector.close()

    # Filter to fresh YouTube URLs only, limit to 5
    init_database()
    youtube_urls: list[str] = []
    conn = get_connection()
    try:
        for trend in raw_trends:
            url = trend.url
            if not url or "youtube.com/watch" not in url:
                continue

            if url in youtube_urls:
                logger.info("Skipping duplicate URL in current batch: %s", url)
                continue

            existing_count = conn.execute(
                "SELECT COUNT(*) AS count FROM clips WHERE url = ?",
                (url,),
            ).fetchone()["count"]
            if existing_count > 0:
                logger.info(
                    "Skipping previously processed URL (%d existing clip rows): %s",
                    existing_count,
                    url,
                )
                continue

            youtube_urls.append(url)
            if len(youtube_urls) >= 5:
                break
    finally:
        conn.close()

    logger.info("Found %d trending YouTube URLs for niche '%s'", len(youtube_urls), niche)

    # Queue each as a clip job
    queued = 0
    for url in youtube_urls:
        process_clip_job.delay(url, niche)
        queued += 1
        logger.info("  Queued: %s", url)

    logger.info("discover_and_queue DONE — queued %d jobs", queued)
    return {"niche": niche, "queued": queued, "urls": youtube_urls}


# ─── Helpers ──────────────────────────────────────────────────────────────


def _get_min_viral_score() -> float:
    raw_threshold = os.getenv("MIN_VIRAL_SCORE", "").strip()
    if not raw_threshold:
        return DEFAULT_MIN_VIRAL_SCORE

    try:
        return float(raw_threshold)
    except ValueError:
        structured_logger.warning(
            "invalid_min_viral_score",
            value=raw_threshold,
            threshold=DEFAULT_MIN_VIRAL_SCORE,
        )
        return DEFAULT_MIN_VIRAL_SCORE


def _apply_viral_score_gate(clip_id: int, threshold: float) -> bool:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT gemini_score FROM clips WHERE id = ?",
            (clip_id,),
        ).fetchone()
        score = float(row["gemini_score"] or 0.0) if row else 0.0
        if score >= threshold:
            return True

        conn.execute(
            "UPDATE clips SET status = 'skipped_low_score' WHERE id = ?",
            (clip_id,),
        )
        conn.commit()
    finally:
        conn.close()

    structured_logger.warning(
        "skipping_low_score_clip",
        clip_id=clip_id,
        score=score,
        threshold=threshold,
    )
    return False


@app.task(name="tasks.run_full_pipeline")
def run_full_pipeline(niches):
    """Run the full clip pipeline (discover + extract + enhance + publish) for each niche."""
    from clip_publisher import publish_ready_clips
    for niche in niches:
        try:
            print(f"[Beat] Starting pipeline for niche: {niche}")
            discover_and_queue(niche)
            published = publish_ready_clips(niche=niche)
            print(f"[Beat] {len(published)} clips published for {niche}")
        except Exception as e:
            print(f"[Beat] Pipeline failed for {niche}: {e}")


def _ensure_clips_table() -> None:
    """Create the clips table if it doesn't exist (idempotent)."""
    conn = get_connection()
    try:
        conn.executescript(
            """
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
        )
        conn.commit()
    finally:
        conn.close()
