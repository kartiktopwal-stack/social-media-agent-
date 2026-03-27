"""Celery application and tasks for distributed daily runs."""

from __future__ import annotations

import uuid
from typing import Any

from celery import Celery, chord, group

from config.settings import settings
from src.orchestrator.pipeline import ContentPipeline, load_niches
from src.utils.logger import get_logger
from src.utils.models import JobStatus

logger = get_logger("celery")

celery_app = Celery(
    "content_empire",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)


@celery_app.task(name="orchestrator.run_niche_pipeline")
def run_niche_pipeline(niche_name: str, run_id: str, dry_run: bool = False) -> dict[str, Any]:
    """Run the content pipeline for a single niche and return summary metrics."""
    niches = load_niches()
    niche = niches.get(niche_name)

    if not niche:
        logger.warning("unknown_niche", niche=niche_name, run_id=run_id)
        return {
            "run_id": run_id,
            "niche": niche_name,
            "total": 0,
            "completed": 0,
            "failed": 1,
            "error": f"Unknown niche: {niche_name}",
        }

    pipeline = ContentPipeline()
    try:
        jobs = pipeline.run(niche, dry_run=dry_run)
        completed = sum(1 for j in jobs if j.status == JobStatus.COMPLETED)
        failed = sum(1 for j in jobs if j.status == JobStatus.FAILED)
        return {
            "run_id": run_id,
            "niche": niche_name,
            "total": len(jobs),
            "completed": completed,
            "failed": failed,
        }
    finally:
        pipeline.close()


@celery_app.task(name="orchestrator.finalize_daily_run")
def finalize_daily_run(results: list[dict[str, Any]], run_id: str) -> dict[str, Any]:
    """Chord callback that aggregates all niche results for a daily run."""
    total = sum(r.get("total", 0) for r in results)
    completed = sum(r.get("completed", 0) for r in results)
    failed = sum(r.get("failed", 0) for r in results)

    summary = {
        "run_id": run_id,
        "niches": len(results),
        "total": total,
        "completed": completed,
        "failed": failed,
    }
    logger.info("daily_run_finalized", **summary)
    return summary


@celery_app.task(name="orchestrator.start_daily_run")
def start_daily_run(niche_names: list[str] | None = None, dry_run: bool = False) -> str:
    """Dispatch a chord for all target niches and return the run id."""
    all_niches = load_niches()
    targets = niche_names or list(all_niches.keys())
    run_id = f"run-{uuid.uuid4().hex[:12]}"

    header = group(run_niche_pipeline.s(niche_name, run_id, dry_run=dry_run) for niche_name in targets)

    # Important: chord callback receives header results as first arg.
    # run_id must be bound explicitly as the second arg.
    chord(header)(finalize_daily_run.s(run_id))

    logger.info("daily_run_dispatched", run_id=run_id, niches=targets, dry_run=dry_run)
    return run_id
