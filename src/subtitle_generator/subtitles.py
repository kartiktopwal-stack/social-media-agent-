"""
src/subtitle_generator/subtitles.py
─────────────────────────────────────────────────────────────────────────────
Subtitle Generator Agent — Generates word-level subtitles from audio
and burns them into the video.
"""

from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path

from moviepy.config import change_settings
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings
from src.core.exceptions import SubtitleGenerationError
from src.utils.logger import get_logger
from src.utils.models import (
    GeneratedScript,
    SubtitleResult,
    SubtitleSegment,
    VideoResult,
    VoiceResult,
)

logger = get_logger("subtitle_generator")

_WINDOWS_IMAGEMAGICK_PATH = (
    r"C:\Program Files\ImageMagick-7.1.1-Q16-HDRI\magick.exe"
)

# Configure MoviePy ImageMagick path before any TextClip usage.
if Path(_WINDOWS_IMAGEMAGICK_PATH).exists():
    IMAGEMAGICK_BINARY = _WINDOWS_IMAGEMAGICK_PATH
else:
    magick_path = shutil.which("magick")
    if not magick_path:
        raise Exception("ImageMagick not found in PATH")
    IMAGEMAGICK_BINARY = magick_path

change_settings({"IMAGEMAGICK_BINARY": IMAGEMAGICK_BINARY})
logger.info(
    "imagemagick_path_detected",
    imagemagick_binary=IMAGEMAGICK_BINARY,
)


class SubtitleGenerator:
    """Generate subtitles from audio and burn them into video."""

    def generate_srt(
        self,
        voice: VoiceResult,
        script: GeneratedScript,
    ) -> SubtitleResult:
        """Generate SRT subtitle file from script text with timing estimates."""
        logger.info("generating_subtitles", topic=script.trend_topic)

        settings.ensure_dirs()
        srt_path = settings.output_dir / "video" / f"{uuid.uuid4().hex}.srt"

        try:
            segments = self._generate_segments_from_text(
                script.full_text, voice.duration_s
            )

            # Write SRT file
            self._write_srt(srt_path, segments)

            result = SubtitleResult(srt_path=srt_path, segments=segments)

            logger.info(
                "subtitles_generated",
                path=str(srt_path),
                segment_count=len(segments),
            )
            return result

        except Exception as e:
            logger.error("subtitle_generation_failed", error=str(e))
            raise SubtitleGenerationError(str(e))

    def _generate_segments_from_text(
        self,
        text: str,
        total_duration: float,
    ) -> list[SubtitleSegment]:
        """Split text into timed subtitle segments."""
        # Split into sentences
        sentences = re.split(r'(?<=[.!?])\s+', text)
        sentences = [s.strip() for s in sentences if s.strip()]

        if not sentences:
            return []

        # Calculate words per sentence for proportional timing
        total_words = sum(len(s.split()) for s in sentences)
        if total_words == 0:
            return []

        segments: list[SubtitleSegment] = []
        current_time = 0.0

        for i, sentence in enumerate(sentences):
            word_count = len(sentence.split())
            duration = (word_count / total_words) * total_duration

            # Split long sentences into chunks of ~6 words for readability
            words = sentence.split()
            chunk_size = 6
            chunks = [
                " ".join(words[j:j + chunk_size])
                for j in range(0, len(words), chunk_size)
            ]

            chunk_duration = duration / len(chunks) if chunks else duration

            for chunk in chunks:
                start = current_time
                end = current_time + chunk_duration

                segments.append(
                    SubtitleSegment(
                        index=len(segments) + 1,
                        start_time=round(start, 3),
                        end_time=round(end, 3),
                        text=chunk,
                    )
                )
                current_time = end

        return segments

    @staticmethod
    def _write_srt(path: Path, segments: list[SubtitleSegment]) -> None:
        """Write segments to an SRT file."""
        lines: list[str] = []
        for seg in segments:
            start = SubtitleGenerator._format_srt_time(seg.start_time)
            end = SubtitleGenerator._format_srt_time(seg.end_time)
            lines.append(str(seg.index))
            lines.append(f"{start} --> {end}")
            lines.append(seg.text)
            lines.append("")

        path.write_text("\n".join(lines), encoding="utf-8")

    @staticmethod
    def _format_srt_time(seconds: float) -> str:
        """Format seconds to SRT time: HH:MM:SS,mmm"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def burn_subtitles(
        self,
        video: VideoResult,
        subtitles: SubtitleResult,
    ) -> VideoResult:
        """Burn SRT subtitles into the video."""
        logger.info("burning_subtitles", video=str(video.video_path))

        output_path = settings.final_dir / f"{uuid.uuid4().hex}.mp4"

        try:
            from moviepy.editor import TextClip, CompositeVideoClip, VideoFileClip

            base = VideoFileClip(str(video.video_path))

            # Create text overlays for each subtitle segment
            txt_clips = []
            for seg in subtitles.segments:
                try:
                    txt = TextClip(
                        seg.text,
                        fontsize=48,
                        color="white",
                        stroke_color="black",
                        stroke_width=2,
                        font="Arial-Bold",
                        size=(base.w - 80, None),
                        method="caption",
                    )
                    txt = txt.set_position(("center", base.h * 0.75))
                    txt = txt.set_start(seg.start_time)
                    txt = txt.set_duration(seg.end_time - seg.start_time)
                    txt_clips.append(txt)
                except Exception as e:
                    logger.warning(
                        "subtitle_clip_failed",
                        segment=seg.index,
                        error=str(e),
                    )

            if txt_clips:
                final = CompositeVideoClip([base, *txt_clips])
            else:
                final = base

            final.write_videofile(
                str(output_path),
                codec="libx264",
                audio_codec="aac",
                fps=30,
                preset="medium",
                threads=4,
                logger=None,
            )

            base.close()
            final.close()
            for tc in txt_clips:
                try:
                    tc.close()
                except Exception:
                    pass

            result = VideoResult(
                video_path=output_path,
                duration_s=video.duration_s,
                resolution=video.resolution,
                has_subtitles=True,
            )

            logger.info("subtitles_burned", path=str(output_path))
            return result

        except Exception as e:
            logger.error("subtitle_burn_failed", error=str(e))
            # Return original video if subtitle burning fails
            logger.warning("returning_video_without_subtitles")
            return video
