"""
src/media_producer/producer.py
─────────────────────────────────────────────────────────────────────────────
Video Generator Agent — Downloads stock footage from Pexels and
assembles final vertical video (1080x1920) with audio overlay.
"""

from __future__ import annotations

import random
import uuid
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings
from src.core.exceptions import VideoProductionError
from src.utils.logger import get_logger
from src.utils.models import GeneratedScript, StockClip, VideoResult, VoiceResult

logger = get_logger("media_producer")

TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920


class PexelsClient:
    """Download stock video clips from Pexels API."""

    BASE_URL = "https://api.pexels.com/videos/search"

    def __init__(self) -> None:
        self._client = httpx.Client(
            timeout=60.0,
            headers={"Authorization": settings.pexels_api_key},
        )

    def search_clips(
        self,
        query: str,
        count: int = 5,
        orientation: str = "portrait",
    ) -> list[StockClip]:
        """Search for stock video clips matching the query."""
        if not settings.pexels_api_key:
            logger.warning("pexels_not_configured")
            return []

        logger.info("searching_pexels", query=query, count=count)

        try:
            resp = self._client.get(
                self.BASE_URL,
                params={
                    "query": query,
                    "per_page": count,
                    "orientation": orientation,
                    "size": "medium",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            clips: list[StockClip] = []
            for video in data.get("videos", []):
                # Prefer HD portrait files
                best_file = None
                for vf in video.get("video_files", []):
                    w = vf.get("width", 0)
                    h = vf.get("height", 0)
                    if h >= w and (best_file is None or w > best_file.get("width", 0)):
                        best_file = vf

                if not best_file:
                    # Fallback to any file
                    files = video.get("video_files", [])
                    if files:
                        best_file = files[0]

                if best_file:
                    clips.append(
                        StockClip(
                            url=best_file["link"],
                            duration_s=video.get("duration", 10),
                            width=best_file.get("width", 1080),
                            height=best_file.get("height", 1920),
                            source="pexels",
                        )
                    )

            logger.info("pexels_clips_found", count=len(clips))
            return clips

        except Exception as e:
            logger.error("pexels_search_failed", error=str(e))
            return []

    def download_clip(self, clip: StockClip) -> Path:
        """Download a clip to local storage."""
        settings.ensure_dirs()
        filename = f"{uuid.uuid4().hex}.mp4"
        local_path = settings.clips_dir / filename

        logger.info("downloading_clip", url=clip.url[:80])

        try:
            with self._client.stream("GET", clip.url) as resp:
                resp.raise_for_status()
                with open(local_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=8192):
                        f.write(chunk)

            clip.local_path = local_path
            logger.info("clip_downloaded", path=str(local_path))
            return local_path

        except Exception as e:
            logger.error("clip_download_failed", error=str(e))
            raise VideoProductionError(f"Failed to download clip: {e}")

    def close(self) -> None:
        self._client.close()


class VideoAssembler:
    """Assemble final video from clips and audio."""

    def assemble(
        self,
        clips: list[StockClip],
        voice: VoiceResult,
        script: GeneratedScript,
    ) -> VideoResult:
        """Assemble clips with voice-over into a final vertical video."""
        logger.info(
            "assembling_video",
            clip_count=len(clips),
            audio_duration=voice.duration_s,
        )

        settings.ensure_dirs()
        output_path = settings.video_dir / f"{uuid.uuid4().hex}.mp4"

        try:
            from moviepy.editor import (
                AudioFileClip,
                ColorClip,
                CompositeVideoClip,
                VideoFileClip,
                concatenate_videoclips,
            )

            # Load audio
            audio = AudioFileClip(str(voice.audio_path))
            target_duration = audio.duration

            # Load and prepare video clips
            video_clips = []
            total_duration = 0.0
            used_background_fallback = False

            for clip in clips:
                if not clip.local_path.exists():
                    continue
                try:
                    vc = VideoFileClip(str(clip.local_path))
                    # Resize to target dimensions
                    vc = vc.resize(height=TARGET_HEIGHT)
                    if vc.w < TARGET_WIDTH:
                        vc = vc.resize(width=TARGET_WIDTH)
                    # Center crop to exact dimensions
                    vc = vc.crop(
                        x_center=vc.w / 2,
                        y_center=vc.h / 2,
                        width=TARGET_WIDTH,
                        height=TARGET_HEIGHT,
                    )
                    video_clips.append(vc)
                    total_duration += vc.duration
                except Exception as e:
                    logger.warning("clip_load_failed", path=str(clip.local_path), error=str(e))

            if not video_clips:
                # Create a solid color background if no clips available
                used_background_fallback = True
                logger.warning("no_clips_available_using_background")
                bg = ColorClip(
                    size=(TARGET_WIDTH, TARGET_HEIGHT),
                    color=(15, 15, 25),
                    duration=target_duration,
                )
                video_clips = [bg]
                total_duration = target_duration

            # Concatenate and loop clips to match audio duration
            if total_duration < target_duration:
                repeats = int(target_duration / total_duration) + 1
                video_clips = video_clips * repeats

            concat = concatenate_videoclips(video_clips, method="compose")
            concat = concat.subclip(0, min(target_duration, concat.duration))

            # Set audio
            final = concat.set_audio(audio)

            footage_mode = (
                "solid_background_fallback" if used_background_fallback else "real_pexels_footage"
            )
            logger.info(
                "video_footage_mode",
                mode=footage_mode,
                assembled_clip_layers=len(video_clips),
            )

            # Write output
            final.write_videofile(
                str(output_path),
                codec="libx264",
                audio_codec="aac",
                fps=30,
                preset="medium",
                threads=4,
                logger=None,
            )

            # Cleanup
            audio.close()
            for vc in video_clips:
                try:
                    vc.close()
                except Exception:
                    pass
            concat.close()
            final.close()

            result = VideoResult(
                video_path=output_path,
                duration_s=target_duration,
                resolution=f"{TARGET_WIDTH}x{TARGET_HEIGHT}",
            )

            logger.info(
                "video_assembled",
                path=str(output_path),
                duration_s=target_duration,
            )
            return result

        except Exception as e:
            logger.error("video_assembly_failed", error=str(e))
            raise VideoProductionError(f"Video assembly failed: {e}")


class MediaProducer:
    """High-level media production: fetch clips + assemble video."""

    def __init__(self) -> None:
        self._pexels = PexelsClient()
        self._assembler = VideoAssembler()

    def produce(
        self,
        script: GeneratedScript,
        voice: VoiceResult,
    ) -> VideoResult:
        """Full media production pipeline."""
        logger.info("media_production_start", topic=script.trend_topic)

        # Build search queries from script keywords/tags
        queries = script.tags[:3] if script.tags else [script.trend_topic]

        all_clips: list[StockClip] = []
        for query in queries:
            clips = self._pexels.search_clips(query, count=3)
            all_clips.extend(clips)

        # Download clips
        downloaded: list[StockClip] = []
        for clip in all_clips[:6]:
            try:
                self._pexels.download_clip(clip)
                downloaded.append(clip)
            except Exception as e:
                logger.warning("clip_download_skipped", error=str(e))

        # Shuffle for variety
        random.shuffle(downloaded)

        # Assemble video
        result = self._assembler.assemble(downloaded, voice, script)

        logger.info(
            "media_production_complete",
            video_path=str(result.video_path),
            duration_s=result.duration_s,
        )
        return result

    def close(self) -> None:
        self._pexels.close()
