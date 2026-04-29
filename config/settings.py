"""
config/settings.py
─────────────────────────────────────────────────────────────────────────────
Typed, validated application settings powered by Pydantic.
"""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv(override=True)

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── System ────────────────────────────────────────────────────────────
    env: Literal["development", "production"] = "development"
    log_level: str = "INFO"
    tz: str = "UTC"

    # ── Database ──────────────────────────────────────────────────────────
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_key: str = ""
    database_url: str = f"sqlite:///{_PROJECT_ROOT / 'data' / 'content_empire.db'}"

    # ── AI / LLM (Groq) ──────────────────────────────────────────────────
    groq_api_key: str = ""
    ai_model: str = "llama-3.3-70b-versatile"
    ai_max_tokens: int = 2000

    # ── AI / LLM (NVIDIA Nemotron) ────────────────────────────────────────
    nvidia_api_key: str = ""
    nemotron_model: str = "nvidia/llama-3.1-nemotron-70b-instruct"

    # ── Voice (edge-tts) ──────────────────────────────────────────────────
    tts_voice: str = "en-US-AriaNeural"

    # ── Trend Sources ─────────────────────────────────────────────────────
    news_api_key: str = ""
    serpapi_key: str = ""
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "ContentEmpire/1.0"
    youtube_api_key: str = ""
    twitter_api_key: str = ""
    twitter_api_secret: str = ""

    # ── Video / Visuals ───────────────────────────────────────────────────
    pexels_api_key: str = ""
    runway_api_key: str = ""
    stability_api_key: str = ""

    # ── Publishing — YouTube ──────────────────────────────────────────────
    youtube_client_id: str = ""
    youtube_client_secret: str = ""


    # ── Storage ───────────────────────────────────────────────────────────
    object_storage_backend: Literal["s3", "local"] = "local"
    object_storage_prefix: str = "content-empire"
    object_storage_public_base_url: str = ""
    local_object_storage_root: str = "data/object_store"
    s3_bucket: str = ""
    s3_region: str = "auto"
    cloudflare_r2_endpoint: str = ""
    cloudflare_r2_access_key: str = ""
    cloudflare_r2_secret_key: str = ""

    # ── Monitoring ────────────────────────────────────────────────────────
    sentry_dsn: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # ── Schedule ──────────────────────────────────────────────────────────
    daily_run_hour: int = 5
    publish_hour: int = 14
    max_videos_per_niche: int = 3

    # ── Dashboard ─────────────────────────────────────────────────────────
    dashboard_require_auth: bool = True
    dashboard_api_key: str = "change_me_for_production"

    # ── Retry / Resilience ────────────────────────────────────────────────
    max_retry_attempts: int = 4
    retry_backoff_seconds: int = 2
    job_claim_timeout_seconds: int = 1800

    # ── Workspace ─────────────────────────────────────────────────────────
    workspace_root: str = "data/workspaces"
    publish_parallelism: int = 4

    # ── Paths (derived) ──────────────────────────────────────────────────
    @property
    def project_root(self) -> Path:
        return _PROJECT_ROOT

    @property
    def output_dir(self) -> Path:
        return _PROJECT_ROOT / "data" / "output"

    @property
    def audio_dir(self) -> Path:
        return self.output_dir / "audio"

    @property
    def clips_dir(self) -> Path:
        return self.output_dir / "clips"

    @property
    def video_dir(self) -> Path:
        return self.output_dir / "video"

    @property
    def final_dir(self) -> Path:
        return self.output_dir / "final"

    @property
    def music_dir(self) -> Path:
        return _PROJECT_ROOT / "data" / "music"

    @property
    def logs_dir(self) -> Path:
        return _PROJECT_ROOT / "data" / "logs"

    def ensure_dirs(self) -> None:
        for d in (
            self.audio_dir,
            self.clips_dir,
            self.video_dir,
            self.final_dir,
            self.music_dir,
            self.logs_dir,
            _PROJECT_ROOT / self.workspace_root,
        ):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
