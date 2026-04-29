"""
celery_app.py
─────────────────────────────────────────────────────────────────────────────
Celery application instance for the AI Content Empire.

Reads broker / backend URLs from .env (CELERY_BROKER_URL, CELERY_RESULT_BACKEND).
Auto-discovers tasks in the `tasks` package.

Start a worker:
    celery -A celery_app worker --loglevel=info

Start the beat scheduler:
    celery -A celery_app beat --loglevel=info
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv(override=True)

from celery import Celery
from celery.schedules import crontab

broker_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

app = Celery(
    "content_empire",
    broker=broker_url,
    backend=result_backend,
    include=["tasks.clip_tasks"],
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

# Beat schedule — run full pipeline 3x daily at 8:00 AM, 2:00 PM, 8:00 PM IST
app.conf.beat_schedule = {
    'run-clip-pipeline-3x-daily': {
        'task': 'tasks.clip_tasks.run_full_pipeline',
        'schedule': crontab(hour='8,14,20', minute=0),
        'args': (['technology'],)
    },
}
