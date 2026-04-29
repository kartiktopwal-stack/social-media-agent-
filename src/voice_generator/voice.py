"""
src/voice_generator/voice.py
─────────────────────────────────────────────────────────────────────────────
Voice Generator Agent — Converts script text to speech using edge-tts
(free Microsoft Edge TTS, no API key required).
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from config.settings import settings
from src.core.exceptions import VoiceGenerationError
from src.utils.logger import get_logger
from src.utils.models import GeneratedScript, NicheConfig, VoiceResult

logger = get_logger("voice_generator")


class VoiceGenerator:
    """Generate voice-overs from script text using edge-tts."""

    UNIVERSAL_FALLBACK_VOICE = "en-US-GuyNeural"
    RETRIES_PER_VOICE = 3

    def generate(
        self,
        script: GeneratedScript,
        niche: NicheConfig,
    ) -> VoiceResult:
        """Generate audio from script text."""
        logger.info("generating_voice", topic=script.trend_topic, niche=niche.name)

        settings.ensure_dirs()
        last_error: Exception | None = None
        voice_retry_order = self._build_voice_retry_order(niche)

        total_attempts = len(voice_retry_order) * self.RETRIES_PER_VOICE
        attempt_counter = 0

        for voice in voice_retry_order:
            for voice_attempt in range(1, self.RETRIES_PER_VOICE + 1):
                attempt_counter += 1
                output_path = settings.audio_dir / f"{uuid.uuid4().hex}.mp3"

                logger.info(
                    "voice_attempt",
                    attempt=attempt_counter,
                    max_attempts=total_attempts,
                    voice_attempt=voice_attempt,
                    retries_per_voice=self.RETRIES_PER_VOICE,
                    voice=voice,
                )

                try:
                    duration = asyncio.run(
                        self._generate_async(script.full_text, voice, output_path)
                    )

                    if not output_path.exists():
                        raise VoiceGenerationError("Audio file was not created")

                    file_size = output_path.stat().st_size
                    if file_size < 1000:
                        raise VoiceGenerationError(
                            f"Audio file too small ({file_size} bytes)"
                        )

                    result = VoiceResult(
                        audio_path=output_path,
                        duration_s=duration,
                        voice_id=voice,
                    )

                    logger.info(
                        "voice_generated",
                        path=str(output_path),
                        duration_s=duration,
                        size_bytes=file_size,
                        voice=voice,
                    )
                    return result

                except Exception as e:
                    last_error = e
                    if output_path.exists():
                        output_path.unlink(missing_ok=True)
                    logger.warning(
                        "voice_attempt_failed",
                        error=str(e),
                        attempt=attempt_counter,
                        max_attempts=total_attempts,
                        voice_attempt=voice_attempt,
                        retries_per_voice=self.RETRIES_PER_VOICE,
                        voice=voice,
                    )

        logger.error("voice_generation_failed", error=str(last_error))
        raise VoiceGenerationError(
            f"Failed to generate audio after {total_attempts} attempts: {last_error}"
        )

    def _build_voice_retry_order(self, niche: NicheConfig) -> list[str]:
        """Build retry order using niche voice first, then universal fallback."""
        retry_order = [niche.tts_voice]
        if niche.tts_voice != self.UNIVERSAL_FALLBACK_VOICE:
            retry_order.append(self.UNIVERSAL_FALLBACK_VOICE)
        return retry_order

    async def _generate_async(
        self,
        text: str,
        voice: str,
        output_path: Path,
    ) -> float:
        """Async edge-tts generation."""
        import edge_tts

        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(str(output_path))

        # Get duration from the generated file
        duration = await self._get_audio_duration(output_path)
        return duration

    @staticmethod
    def _get_pydub_audio_segment():
        """Import pydub with ffmpeg auto-configured (no RuntimeWarning)."""
        import os
        import warnings

        # Suppress the RuntimeWarning pydub emits at import when ffmpeg isn't on PATH
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            from pydub import AudioSegment

        # Override converter if it doesn't point to a real file
        if not os.path.isfile(AudioSegment.converter):
            # 1. Try the imageio_ffmpeg bundled binary (already a project dep)
            try:
                import imageio_ffmpeg
                ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
                if ffmpeg_path and os.path.isfile(ffmpeg_path):
                    AudioSegment.converter = ffmpeg_path
                    AudioSegment.ffprobe = ffmpeg_path
                    return AudioSegment
            except ImportError:
                pass

            # 2. Fall back to explicit env var
            env_path = os.getenv("FFMPEG_PATH")
            if env_path and os.path.isfile(env_path):
                AudioSegment.converter = env_path
                AudioSegment.ffprobe = env_path

        return AudioSegment

    @staticmethod
    async def _get_audio_duration(path: Path) -> float:
        """Get audio duration using pydub."""
        try:
            AudioSegment = VoiceGenerator._get_pydub_audio_segment()
            audio = AudioSegment.from_mp3(str(path))
            return len(audio) / 1000.0
        except Exception:
            # Estimate from file size (~16kbps for edge-tts mp3)
            file_size = path.stat().st_size
            return file_size / (16 * 1024 / 8)

    @staticmethod
    def list_voices() -> list[dict[str, str]]:
        """List available edge-tts voices."""
        import edge_tts

        voices = asyncio.run(edge_tts.list_voices())
        return [
            {
                "name": v["ShortName"],
                "gender": v["Gender"],
                "locale": v["Locale"],
            }
            for v in voices
            if v["Locale"].startswith("en-")
        ]
