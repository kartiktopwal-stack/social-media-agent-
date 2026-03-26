"""
src/dashboard/app.py
─────────────────────────────────────────────────────────────────────────────
FastAPI monitoring dashboard with status endpoints.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config.settings import settings
from src.core.db import get_connection
from src.utils.logger import get_logger

logger = get_logger("dashboard")

app = FastAPI(
    title="AI Content Empire Dashboard",
    description="Monitoring dashboard for the automated content pipeline",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def verify_api_key(x_api_key: str = Header(default="")) -> str:
    """Verify dashboard API key if auth is required."""
    if settings.dashboard_require_auth:
        if x_api_key != settings.dashboard_api_key:
            raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "name": "AI Content Empire",
        "status": "running",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "healthy",
        "environment": settings.env,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/api/stats")
async def get_stats(_: str = Depends(verify_api_key)) -> dict:
    """Get overall pipeline statistics."""
    try:
        conn = get_connection()

        total_jobs = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        completed = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE status = 'completed'"
        ).fetchone()[0]
        failed = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE status = 'failed'"
        ).fetchone()[0]
        published = conn.execute(
            "SELECT COUNT(*) FROM publish_log WHERE success = 1"
        ).fetchone()[0]

        conn.close()

        return {
            "total_jobs": total_jobs,
            "completed": completed,
            "failed": failed,
            "published": published,
            "success_rate": round(completed / total_jobs * 100, 1) if total_jobs > 0 else 0,
        }

    except Exception as e:
        logger.error("stats_query_failed", error=str(e))
        return {"error": str(e)}


@app.get("/api/jobs")
async def list_jobs(
    limit: int = 20,
    status: str | None = None,
    niche: str | None = None,
    _: str = Depends(verify_api_key),
) -> list[dict]:
    """List recent pipeline jobs."""
    try:
        conn = get_connection()

        query = "SELECT * FROM jobs WHERE 1=1"
        params: list[str] = []

        if status:
            query += " AND status = ?"
            params.append(status)
        if niche:
            query += " AND niche = ?"
            params.append(niche)

        query += " ORDER BY started_at DESC LIMIT ?"
        params.append(str(limit))

        rows = conn.execute(query, params).fetchall()
        conn.close()

        return [dict(row) for row in rows]

    except Exception as e:
        logger.error("jobs_query_failed", error=str(e))
        return []


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str, _: str = Depends(verify_api_key)) -> dict:
    """Get details for a specific job."""
    try:
        conn = get_connection()
        row = conn.execute(
            "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        conn.close()

        if not row:
            raise HTTPException(status_code=404, detail="Job not found")

        return dict(row)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("job_query_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/publish-log")
async def publish_log(
    limit: int = 20,
    _: str = Depends(verify_api_key),
) -> list[dict]:
    """Get recent publish log entries."""
    try:
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM publish_log ORDER BY published_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()

        return [dict(row) for row in rows]

    except Exception as e:
        logger.error("publish_log_query_failed", error=str(e))
        return []


@app.get("/api/trends")
async def recent_trends(
    limit: int = 20,
    niche: str | None = None,
    _: str = Depends(verify_api_key),
) -> list[dict]:
    """Get recently collected trends."""
    try:
        conn = get_connection()

        query = "SELECT * FROM trends"
        params: list[str] = []

        if niche:
            query += " WHERE niche = ?"
            params.append(niche)

        query += " ORDER BY collected_at DESC LIMIT ?"
        params.append(str(limit))

        rows = conn.execute(query, params).fetchall()
        conn.close()

        return [dict(row) for row in rows]

    except Exception as e:
        logger.error("trends_query_failed", error=str(e))
        return []


@app.get("/api/config")
async def get_config(_: str = Depends(verify_api_key)) -> dict:
    """Get current configuration (non-sensitive fields only)."""
    return {
        "environment": settings.env,
        "log_level": settings.log_level,
        "daily_run_hour": settings.daily_run_hour,
        "publish_hour": settings.publish_hour,
        "max_videos_per_niche": settings.max_videos_per_niche,
        "storage_backend": settings.object_storage_backend,
        "ai_model": settings.ai_model,
        "tts_voice": settings.tts_voice,
        "apis_configured": {
            "gemini": bool(settings.gemini_api_key),
            "pexels": bool(settings.pexels_api_key),
            "newsapi": bool(settings.news_api_key),
            "youtube": bool(settings.youtube_api_key),
            "reddit": bool(settings.reddit_client_id),
            "twitter": bool(settings.twitter_api_key),
            "tiktok": bool(settings.tiktok_client_key),
            "instagram": bool(settings.meta_app_id),
            "telegram": bool(settings.telegram_bot_token),
        },
    }
