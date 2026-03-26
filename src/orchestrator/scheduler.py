"""
src/orchestrator/scheduler.py
─────────────────────────────────────────────────────────────────────────────
Scheduler for fully automated daily content production runs.
Uses APScheduler for cron-like scheduling.
"""

from __future__ import annotations

import signal
import sys
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from config.settings import settings
from src.core.db import init_database
from src.orchestrator.pipeline import DailyRunner
from src.utils.logger import configure_logging, get_logger

logger = get_logger("scheduler")


def daily_production_job() -> None:
    """Execute the full daily content production pipeline."""
    logger.info("scheduled_run_start", time=datetime.utcnow().isoformat())

    try:
        runner = DailyRunner()
        report = runner.run_all(dry_run=False)
        logger.info(
            "scheduled_run_complete",
            total=report.total_jobs,
            completed=report.completed,
            failed=report.failed,
            published=report.published,
        )
        runner.close()
    except Exception as e:
        logger.error("scheduled_run_failed", error=str(e))


def start_scheduler() -> None:
    """Start the APScheduler with daily production cron."""
    configure_logging(level=settings.log_level, environment=settings.env)
    init_database()

    scheduler = BlockingScheduler(timezone="UTC")

    # Daily production run
    scheduler.add_job(
        daily_production_job,
        trigger=CronTrigger(hour=settings.daily_run_hour, minute=0),
        id="daily_production",
        name="Daily Content Production",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    logger.info(
        "scheduler_configured",
        daily_run_hour=settings.daily_run_hour,
        publish_hour=settings.publish_hour,
    )

    # Graceful shutdown
    def shutdown(signum: int, frame: object) -> None:
        logger.info("scheduler_shutting_down")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logger.info("scheduler_started")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("scheduler_stopped")
