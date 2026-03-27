"""
src/orchestrator/pipeline.py
─────────────────────────────────────────────────────────────────────────────
Master pipeline that orchestrates all agents end-to-end:
Trends → Script → Voice → Video → Subtitles → Publish
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

import yaml

from config.settings import settings
from src.core.db import get_connection
from src.core.exceptions import PipelineError
from src.media_producer.producer import MediaProducer
from src.publisher.publisher import AutoPublisher
from src.script_generator.generator import ScriptGenerator
from src.subtitle_generator.subtitles import SubtitleGenerator
from src.trend_engine.collector import TrendAggregator
from src.utils.logger import get_logger
from src.utils.models import (
    DailyReport,
    FinalVideo,
    JobStatus,
    NicheConfig,
    PipelineJob,
    Platform,
)
from src.voice_generator.voice import VoiceGenerator

logger = get_logger("pipeline")


def load_niches() -> dict[str, NicheConfig]:
    """Load niche configurations from YAML file."""
    niches_path = settings.project_root / "config" / "niches.yaml"
    if not niches_path.exists():
        logger.warning("niches_yaml_not_found", path=str(niches_path))
        return {}

    with open(niches_path) as f:
        data = yaml.safe_load(f)

    niches: dict[str, NicheConfig] = {}
    for name, cfg in data.get("niches", {}).items():
        cfg["name"] = name
        niches[name] = NicheConfig(**cfg)

    logger.info("niches_loaded", count=len(niches))
    return niches


class ContentPipeline:
    """Single-niche content production pipeline."""

    def __init__(self) -> None:
        self._trend_aggregator = TrendAggregator()
        self._script_generator = ScriptGenerator()
        self._voice_generator = VoiceGenerator()
        self._media_producer = MediaProducer()
        self._subtitle_generator = SubtitleGenerator()
        self._publisher = AutoPublisher()

    def run(
        self,
        niche: NicheConfig,
        dry_run: bool = False,
        max_videos: int | None = None,
    ) -> list[PipelineJob]:
        """Run the full pipeline for a single niche."""
        max_videos = max_videos or settings.max_videos_per_niche
        logger.info(
            "pipeline_start",
            niche=niche.name,
            max_videos=max_videos,
            dry_run=dry_run,
        )

        jobs: list[PipelineJob] = []

        # Step 1: Collect and score trends
        try:
            scored_trends = self._trend_aggregator.run(niche)
        except Exception as e:
            logger.error("trend_collection_failed", niche=niche.name, error=str(e))
            return jobs

        # Process top N trends
        for trend in scored_trends[:max_videos]:
            job = PipelineJob(
                job_id=f"job-{uuid.uuid4().hex[:12]}",
                niche=niche.name,
                trend=trend,
                started_at=datetime.utcnow(),
            )

            try:
                # Step 2: Generate script
                job.status = JobStatus.GENERATING_SCRIPT
                logger.info("step_start", job_id=job.job_id, step=job.status.value, topic=trend.topic)
                script = self._script_generator.generate(trend, niche, Platform.YOUTUBE)
                job.script = script
                logger.info("step_complete", job_id=job.job_id, step=job.status.value, topic=trend.topic)

                if dry_run:
                    logger.info("dry_run_short_circuit", job_id=job.job_id, topic=trend.topic)
                    settings.ensure_dirs()
                    placeholder_path = settings.final_dir / f"dry_run_{job.job_id}.mp4"
                    final = FinalVideo(
                        video_path=placeholder_path,
                        title=script.title,
                        description=script.description,
                        tags=script.tags,
                        niche=niche.name,
                        trend_topic=trend.topic,
                        script=script,
                    )
                    final.publish_results = self._publisher.publish_all(final, niche, dry_run=True)
                    job.final_video = final
                    job.status = JobStatus.COMPLETED
                    job.completed_at = datetime.utcnow()
                    self._save_job(job)
                    jobs.append(job)
                    continue

                # Step 3: Generate voice
                job.status = JobStatus.GENERATING_VOICE
                logger.info("step_start", job_id=job.job_id, step=job.status.value, topic=trend.topic)
                voice = self._voice_generator.generate(script, niche)
                job.voice = voice
                logger.info("step_complete", job_id=job.job_id, step=job.status.value, topic=trend.topic)

                # Step 4: Produce video
                job.status = JobStatus.PRODUCING_VIDEO
                logger.info("step_start", job_id=job.job_id, step=job.status.value, topic=trend.topic)
                video = self._media_producer.produce(script, voice)
                job.video = video
                logger.info("step_complete", job_id=job.job_id, step=job.status.value, topic=trend.topic)

                # Step 5: Generate and burn subtitles
                job.status = JobStatus.GENERATING_SUBTITLES
                logger.info("step_start", job_id=job.job_id, step=job.status.value, topic=trend.topic)
                subtitles = self._subtitle_generator.generate_srt(voice, script)
                job.subtitles = subtitles
                final_video_result = self._subtitle_generator.burn_subtitles(video, subtitles)
                logger.info("step_complete", job_id=job.job_id, step=job.status.value, topic=trend.topic)

                # Build FinalVideo
                final = FinalVideo(
                    video_path=final_video_result.video_path,
                    title=script.title,
                    description=script.description,
                    tags=script.tags,
                    niche=niche.name,
                    trend_topic=trend.topic,
                    script=script,
                    voice=voice,
                    subtitles=subtitles,
                )
                job.final_video = final

                # Step 6: Publish
                job.status = JobStatus.PUBLISHING
                logger.info(
                    "step_start",
                    job_id=job.job_id,
                    step=job.status.value,
                    topic=trend.topic,
                    dry_run=dry_run,
                )
                publish_results = self._publisher.publish_all(
                    final, niche, dry_run=dry_run
                )
                final.publish_results = publish_results
                logger.info("step_complete", job_id=job.job_id, step=job.status.value, topic=trend.topic)

                job.status = JobStatus.COMPLETED
                job.completed_at = datetime.utcnow()
                logger.info(
                    "job_completed",
                    job_id=job.job_id,
                    topic=trend.topic,
                    published=sum(1 for r in publish_results if r.success),
                )

            except Exception as e:
                job.status = JobStatus.FAILED
                job.error = str(e)
                job.completed_at = datetime.utcnow()
                logger.error(
                    "job_failed",
                    job_id=job.job_id,
                    topic=trend.topic,
                    error=str(e),
                )

            # Save job to database
            self._save_job(job)
            jobs.append(job)

        logger.info(
            "pipeline_complete",
            niche=niche.name,
            total=len(jobs),
            completed=sum(1 for j in jobs if j.status == JobStatus.COMPLETED),
            failed=sum(1 for j in jobs if j.status == JobStatus.FAILED),
        )
        return jobs

    @staticmethod
    def _save_job(job: PipelineJob) -> None:
        """Persist job record to database."""
        try:
            conn = get_connection()
            conn.execute(
                """
                INSERT OR REPLACE INTO jobs
                    (job_id, niche, status, trend_topic, audio_path, video_path,
                     final_path, error, started_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.job_id,
                    job.niche,
                    job.status.value,
                    job.trend.topic if job.trend else "",
                    str(job.voice.audio_path) if job.voice else "",
                    str(job.video.video_path) if job.video else "",
                    str(job.final_video.video_path) if job.final_video else "",
                    job.error,
                    job.started_at.isoformat() if job.started_at else None,
                    job.completed_at.isoformat() if job.completed_at else None,
                ),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning("job_save_failed", job_id=job.job_id, error=str(e))

    def close(self) -> None:
        self._trend_aggregator.close()
        self._media_producer.close()


class DailyRunner:
    """Run the pipeline for all configured niches."""

    def __init__(self) -> None:
        self._pipeline = ContentPipeline()

    def run_all(
        self,
        niche_names: list[str] | None = None,
        dry_run: bool = False,
    ) -> DailyReport:
        """Run pipeline for all (or selected) niches and produce a report."""
        all_niches = load_niches()
        target = niche_names or list(all_niches.keys())

        logger.info("daily_run_start", niches=target, dry_run=dry_run)

        all_jobs: list[PipelineJob] = []
        niches_covered: list[str] = []

        for name in target:
            niche = all_niches.get(name)
            if not niche:
                logger.warning("unknown_niche", name=name)
                continue

            try:
                jobs = self._pipeline.run(niche, dry_run=dry_run)
                all_jobs.extend(jobs)
                niches_covered.append(name)
            except Exception as e:
                logger.error("niche_run_failed", niche=name, error=str(e))

        # Build report
        completed_jobs = [j for j in all_jobs if j.status == JobStatus.COMPLETED]
        failed_jobs = [j for j in all_jobs if j.status == JobStatus.FAILED]
        published = sum(
            1
            for j in completed_jobs
            if j.final_video and any(r.success for r in j.final_video.publish_results)
        )

        top_job = max(
            all_jobs,
            key=lambda j: j.trend.virality_score if j.trend else 0,
            default=None,
        )

        report = DailyReport(
            date=datetime.utcnow().strftime("%Y-%m-%d"),
            total_jobs=len(all_jobs),
            completed=len(completed_jobs),
            failed=len(failed_jobs),
            published=published,
            top_topic=top_job.trend.topic if top_job and top_job.trend else "N/A",
            top_virality_score=top_job.trend.virality_score if top_job and top_job.trend else 0,
            niches_covered=niches_covered,
            jobs=all_jobs,
            errors=[j.error for j in failed_jobs if j.error],
        )

        # Save report to disk
        self._save_report(report)

        logger.info(
            "daily_run_complete",
            total=report.total_jobs,
            completed=report.completed,
            failed=report.failed,
            published=report.published,
        )
        return report

    @staticmethod
    def _save_report(report: DailyReport) -> None:
        """Save daily report as JSON."""
        try:
            import json

            settings.ensure_dirs()
            report_path = settings.logs_dir / f"report_{report.date}.json"
            report_path.write_text(
                json.dumps(report.model_dump(mode="json"), indent=2, default=str),
                encoding="utf-8",
            )
            logger.info("report_saved", path=str(report_path))
        except Exception as e:
            logger.warning("report_save_failed", error=str(e))

    def close(self) -> None:
        self._pipeline.close()
