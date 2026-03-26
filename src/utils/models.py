"""
src/utils/models.py
─────────────────────────────────────────────────────────────────────────────
Shared Pydantic data models used across all agents.
"""

from __future__ import annotations

import enum
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


# ─── Enums ────────────────────────────────────────────────────────────────────

class Platform(str, enum.Enum):
    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    TWITTER = "twitter"


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    COLLECTING_TRENDS = "collecting_trends"
    GENERATING_SCRIPT = "generating_script"
    GENERATING_VOICE = "generating_voice"
    PRODUCING_VIDEO = "producing_video"
    GENERATING_SUBTITLES = "generating_subtitles"
    PUBLISHING = "publishing"
    COMPLETED = "completed"
    FAILED = "failed"


class TrendSource(str, enum.Enum):
    GOOGLE_TRENDS = "google_trends"
    REDDIT = "reddit"
    YOUTUBE = "youtube"
    NEWSAPI = "newsapi"
    HACKERNEWS = "hackernews"


# ─── Niche Config ─────────────────────────────────────────────────────────────

class NicheConfig(BaseModel):
    name: str
    display_name: str
    description: str
    tone: str = "informative and engaging"
    keywords: list[str] = Field(default_factory=list)
    subreddits: list[str] = Field(default_factory=list)
    youtube_category_id: str = "28"
    news_category: str = "technology"
    tts_voice: str = "en-US-AriaNeural"
    script_style: str = "dramatic_reveal"
    posting_times: dict[str, int] = Field(default_factory=lambda: {"youtube": 14})
    platforms: dict[str, dict[str, str]] = Field(default_factory=dict)


# ─── Trend Models ─────────────────────────────────────────────────────────────

class RawTrend(BaseModel):
    topic: str
    source: TrendSource
    url: str = ""
    description: str = ""
    popularity_score: float = 0.0
    collected_at: datetime = Field(default_factory=datetime.utcnow)


class ScoredTrend(BaseModel):
    niche: str = ""
    topic: str
    description: str = ""
    virality_score: float = 0.0
    reasoning: str = ""
    sources: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    collected_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Script Models ────────────────────────────────────────────────────────────

class ScriptSections(BaseModel):
    hook: str = ""
    body: list[str] = Field(default_factory=list)
    cta: str = ""


class GeneratedScript(BaseModel):
    trend_topic: str
    niche: str
    platform: Platform
    title: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    sections: ScriptSections = Field(default_factory=ScriptSections)
    full_text: str = ""
    word_count: int = 0
    estimated_duration_s: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Voice Models ─────────────────────────────────────────────────────────────

class VoiceResult(BaseModel):
    audio_path: Path
    duration_s: float = 0.0
    voice_id: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Video Models ─────────────────────────────────────────────────────────────

class StockClip(BaseModel):
    url: str
    local_path: Path = Path()
    duration_s: float = 0.0
    width: int = 0
    height: int = 0
    source: str = "pexels"


class VideoResult(BaseModel):
    video_path: Path
    duration_s: float = 0.0
    resolution: str = "1080x1920"
    has_subtitles: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Subtitle Models ─────────────────────────────────────────────────────────

class SubtitleSegment(BaseModel):
    index: int
    start_time: float
    end_time: float
    text: str


class SubtitleResult(BaseModel):
    srt_path: Path
    segments: list[SubtitleSegment] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Publishing Models ───────────────────────────────────────────────────────

class PublishResult(BaseModel):
    platform: Platform
    success: bool = False
    post_id: str = ""
    post_url: str = ""
    error: str = ""
    published_at: Optional[datetime] = None


class FinalVideo(BaseModel):
    video_path: Path
    title: str
    description: str
    tags: list[str] = Field(default_factory=list)
    niche: str = ""
    trend_topic: str = ""
    script: Optional[GeneratedScript] = None
    voice: Optional[VoiceResult] = None
    subtitles: Optional[SubtitleResult] = None
    publish_results: list[PublishResult] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Pipeline / Daily Report ─────────────────────────────────────────────────

class PipelineJob(BaseModel):
    job_id: str = ""
    niche: str
    trend: Optional[ScoredTrend] = None
    script: Optional[GeneratedScript] = None
    voice: Optional[VoiceResult] = None
    video: Optional[VideoResult] = None
    subtitles: Optional[SubtitleResult] = None
    final_video: Optional[FinalVideo] = None
    status: JobStatus = JobStatus.PENDING
    error: str = ""
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class DailyReport(BaseModel):
    date: str
    total_jobs: int = 0
    completed: int = 0
    failed: int = 0
    published: int = 0
    top_topic: str = ""
    top_virality_score: float = 0.0
    niches_covered: list[str] = Field(default_factory=list)
    jobs: list[PipelineJob] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
