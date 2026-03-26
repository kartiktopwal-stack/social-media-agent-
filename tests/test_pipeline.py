"""
tests/test_pipeline.py
─────────────────────────────────────────────────────────────────────────────
Unit tests for the AI Content Empire pipeline.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.utils.models import (
    DailyReport,
    FinalVideo,
    GeneratedScript,
    JobStatus,
    NicheConfig,
    PipelineJob,
    Platform,
    PublishResult,
    RawTrend,
    ScoredTrend,
    ScriptSections,
    StockClip,
    SubtitleResult,
    SubtitleSegment,
    TrendSource,
    VideoResult,
    VoiceResult,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_niche() -> NicheConfig:
    return NicheConfig(
        name="technology",
        display_name="Tech & AI",
        description="Latest technology trends",
        tone="excited, informative",
        keywords=["AI", "machine learning", "startups"],
        subreddits=["technology", "programming"],
        youtube_category_id="28",
        news_category="technology",
        tts_voice="en-US-GuyNeural",
        script_style="dramatic_reveal",
    )


@pytest.fixture
def sample_trend() -> ScoredTrend:
    return ScoredTrend(
        niche="technology",
        topic="GPT-5 Released with Revolutionary Capabilities",
        description="OpenAI announces GPT-5",
        virality_score=9.5,
        reasoning="Extremely high interest in AI",
        sources=["hackernews", "reddit"],
        keywords=["GPT-5", "AI", "OpenAI"],
    )


@pytest.fixture
def sample_script() -> GeneratedScript:
    return GeneratedScript(
        trend_topic="GPT-5 Released",
        niche="technology",
        platform=Platform.YOUTUBE,
        title="GPT-5 Just Changed Everything",
        description="The AI revolution continues",
        tags=["AI", "GPT5", "technology"],
        sections=ScriptSections(
            hook="GPT-5 just dropped and it's not what anyone expected...",
            body=[
                "OpenAI has released GPT-5 with mind-blowing capabilities.",
                "It can now reason like a human in real-time.",
                "Experts are calling this the biggest leap in AI history.",
                "Here's what this means for you and your career.",
            ],
            cta="Follow for more AI updates! Comment what you think below!",
        ),
        full_text="GPT-5 just dropped... OpenAI has released GPT-5...",
        word_count=85,
        estimated_duration_s=34.0,
    )


@pytest.fixture
def sample_voice(tmp_path: Path) -> VoiceResult:
    audio_file = tmp_path / "test_audio.mp3"
    audio_file.write_bytes(b"\x00" * 10000)
    return VoiceResult(
        audio_path=audio_file,
        duration_s=34.0,
        voice_id="en-US-GuyNeural",
    )


# ─── Model Tests ──────────────────────────────────────────────────────────────

class TestModels:
    def test_niche_config_creation(self, sample_niche: NicheConfig) -> None:
        assert sample_niche.name == "technology"
        assert sample_niche.display_name == "Tech & AI"
        assert len(sample_niche.keywords) == 3
        assert sample_niche.tts_voice == "en-US-GuyNeural"

    def test_scored_trend_creation(self, sample_trend: ScoredTrend) -> None:
        assert sample_trend.virality_score == 9.5
        assert sample_trend.niche == "technology"
        assert len(sample_trend.sources) == 2

    def test_script_sections(self) -> None:
        sections = ScriptSections(
            hook="Did you know?",
            body=["Point 1", "Point 2"],
            cta="Follow now!",
        )
        assert sections.hook == "Did you know?"
        assert len(sections.body) == 2

    def test_generated_script(self, sample_script: GeneratedScript) -> None:
        assert sample_script.platform == Platform.YOUTUBE
        assert sample_script.word_count == 85
        assert sample_script.estimated_duration_s == 34.0

    def test_voice_result(self, sample_voice: VoiceResult) -> None:
        assert sample_voice.duration_s == 34.0
        assert sample_voice.audio_path.exists()

    def test_video_result(self) -> None:
        result = VideoResult(
            video_path=Path("/tmp/test.mp4"),
            duration_s=60.0,
            resolution="1080x1920",
            has_subtitles=False,
        )
        assert result.duration_s == 60.0
        assert result.resolution == "1080x1920"

    def test_publish_result(self) -> None:
        result = PublishResult(
            platform=Platform.YOUTUBE,
            success=True,
            post_id="abc123",
            post_url="https://youtube.com/shorts/abc123",
            published_at=datetime.utcnow(),
        )
        assert result.success is True
        assert result.platform == Platform.YOUTUBE

    def test_pipeline_job(self, sample_trend: ScoredTrend) -> None:
        job = PipelineJob(
            job_id="job-test123",
            niche="technology",
            trend=sample_trend,
            status=JobStatus.PENDING,
        )
        assert job.status == JobStatus.PENDING
        assert job.trend is not None
        assert job.trend.virality_score == 9.5

    def test_daily_report(self) -> None:
        report = DailyReport(
            date="2026-03-26",
            total_jobs=5,
            completed=4,
            failed=1,
            published=3,
            top_topic="AI Revolution",
            top_virality_score=9.8,
            niches_covered=["technology", "finance"],
        )
        assert report.total_jobs == 5
        assert report.completed == 4
        assert len(report.niches_covered) == 2

    def test_raw_trend(self) -> None:
        trend = RawTrend(
            topic="Test Topic",
            source=TrendSource.HACKERNEWS,
            url="https://example.com",
            popularity_score=7.5,
        )
        assert trend.source == TrendSource.HACKERNEWS
        assert trend.popularity_score == 7.5

    def test_platform_enum(self) -> None:
        assert Platform.YOUTUBE.value == "youtube"
        assert Platform.INSTAGRAM.value == "instagram"
        assert Platform.TIKTOK.value == "tiktok"
        assert Platform.TWITTER.value == "twitter"

    def test_job_status_enum(self) -> None:
        assert JobStatus.PENDING.value == "pending"
        assert JobStatus.COMPLETED.value == "completed"
        assert JobStatus.FAILED.value == "failed"

    def test_final_video(self, sample_script: GeneratedScript) -> None:
        final = FinalVideo(
            video_path=Path("/tmp/final.mp4"),
            title="Test Video",
            description="A test video",
            tags=["test"],
            niche="technology",
            trend_topic="Test Topic",
            script=sample_script,
        )
        assert final.title == "Test Video"
        assert final.script is not None


# ─── Subtitle Tests ───────────────────────────────────────────────────────────

class TestSubtitleGenerator:
    def test_format_srt_time(self) -> None:
        from src.subtitle_generator.subtitles import SubtitleGenerator

        gen = SubtitleGenerator()
        assert gen._format_srt_time(0.0) == "00:00:00,000"
        assert gen._format_srt_time(1.5) == "00:00:01,500"
        assert gen._format_srt_time(65.123) == "00:01:05,123"
        assert gen._format_srt_time(3661.0) == "01:01:01,000"

    def test_generate_segments_from_text(self) -> None:
        from src.subtitle_generator.subtitles import SubtitleGenerator

        gen = SubtitleGenerator()
        text = "This is sentence one. This is sentence two. And this is three."
        segments = gen._generate_segments_from_text(text, 30.0)

        assert len(segments) > 0
        assert segments[0].start_time == 0.0
        assert segments[-1].end_time <= 30.0 + 0.01

    def test_write_srt(self, tmp_path: Path) -> None:
        from src.subtitle_generator.subtitles import SubtitleGenerator

        gen = SubtitleGenerator()
        segments = [
            SubtitleSegment(index=1, start_time=0.0, end_time=2.0, text="Hello world"),
            SubtitleSegment(index=2, start_time=2.0, end_time=4.0, text="Second line"),
        ]
        srt_path = tmp_path / "test.srt"
        gen._write_srt(srt_path, segments)

        content = srt_path.read_text()
        assert "Hello world" in content
        assert "00:00:00,000 --> 00:00:02,000" in content


# ─── Script Generator Tests ──────────────────────────────────────────────────

class TestScriptGenerator:
    def test_build_full_text(self) -> None:
        from src.script_generator.generator import ScriptGenerator

        gen = ScriptGenerator()
        sections = ScriptSections(
            hook="Start here.",
            body=["Point one.", "Point two."],
            cta="Follow now!",
        )
        text = gen._build_full_text(sections)
        assert "Start here." in text
        assert "Point one." in text
        assert "Follow now!" in text

    def test_template_generation(
        self,
        sample_trend: ScoredTrend,
        sample_niche: NicheConfig,
    ) -> None:
        from src.script_generator.generator import ScriptGenerator

        gen = ScriptGenerator()
        script = gen._generate_template(sample_trend, sample_niche, Platform.YOUTUBE)

        assert script.trend_topic == sample_trend.topic
        assert script.niche == sample_niche.name
        assert script.word_count > 0
        assert script.estimated_duration_s > 0
        assert script.sections.hook != ""
        assert len(script.sections.body) > 0


# ─── Trend Engine Tests ──────────────────────────────────────────────────────

class TestViralityScorer:
    def test_heuristic_scoring(self, sample_niche: NicheConfig) -> None:
        from src.trend_engine.collector import ViralityScorer

        scorer = ViralityScorer()
        raw_trends = [
            RawTrend(
                topic="AI breakthrough in machine learning",
                source=TrendSource.HACKERNEWS,
                popularity_score=7.0,
            ),
            RawTrend(
                topic="New cooking recipe viral",
                source=TrendSource.REDDIT,
                popularity_score=3.0,
            ),
        ]

        scored = scorer._heuristic_score(raw_trends, sample_niche)
        assert len(scored) == 2
        # The AI topic should score higher due to keyword match
        assert scored[0].virality_score >= scored[1].virality_score


# ─── Config Tests ─────────────────────────────────────────────────────────────

class TestConfig:
    def test_settings_loaded(self) -> None:
        from config.settings import settings

        assert settings.env in ("development", "production")
        assert settings.log_level in ("DEBUG", "INFO", "WARNING", "ERROR")
        assert settings.max_videos_per_niche > 0

    def test_niches_yaml_load(self) -> None:
        from src.orchestrator.pipeline import load_niches

        niches = load_niches()
        assert len(niches) > 0
        assert "technology" in niches
        tech = niches["technology"]
        assert tech.display_name == "Tech & AI"
        assert len(tech.keywords) > 0

    def test_settings_paths(self) -> None:
        from config.settings import settings

        assert settings.project_root.exists()
        assert settings.output_dir.parent.name == "data"


# ─── Database Tests ───────────────────────────────────────────────────────────

class TestDatabase:
    def test_init_database(self, tmp_path: Path) -> None:
        import sqlite3

        from src.core.db import _SCHEMA

        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript(_SCHEMA)
        conn.commit()

        # Verify tables exist
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = [t[0] for t in tables]

        assert "trends" in table_names
        assert "scripts" in table_names
        assert "jobs" in table_names
        assert "publish_log" in table_names

        conn.close()


# ─── Exception Tests ─────────────────────────────────────────────────────────

class TestExceptions:
    def test_agent_error(self) -> None:
        from src.core.exceptions import AgentError

        err = AgentError("TestAgent", "something went wrong")
        assert "TestAgent" in str(err)
        assert "something went wrong" in str(err)

    def test_trend_collection_error(self) -> None:
        from src.core.exceptions import TrendCollectionError

        err = TrendCollectionError("no data")
        assert "TrendFinder" in str(err)

    def test_api_key_missing_error(self) -> None:
        from src.core.exceptions import APIKeyMissingError

        err = APIKeyMissingError("GEMINI_API_KEY")
        assert "GEMINI_API_KEY" in str(err)

    def test_publishing_error(self) -> None:
        from src.core.exceptions import PublishingError

        err = PublishingError("youtube", "auth failed")
        assert "youtube" in str(err)
        assert "AutoPublisher" in str(err)
