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

    VOICE_PRIORITY = [
        "en-US-AriaNeural",
        "en-US-GuyNeural",
        "en-US-JennyNeural",
    ]

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

        for attempt, voice in enumerate(voice_retry_order, start=1):
            output_path = settings.audio_dir / f"{uuid.uuid4().hex}.mp3"

            logger.info(
                "voice_attempt",
                attempt=attempt,
                max_attempts=len(voice_retry_order),
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
                    attempt=attempt,
                    max_attempts=len(voice_retry_order),
                    voice=voice,
                )

        logger.error("voice_generation_failed", error=str(last_error))
        raise VoiceGenerationError(
            f"Failed to generate audio after {len(voice_retry_order)} attempts:"
            f" {last_error}"
        )

    def _build_voice_retry_order(self, niche: NicheConfig) -> list[str]:
        """Build retry order from the approved voice priority list only."""
        return list(self.VOICE_PRIORITY)

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
    async def _get_audio_duration(path: Path) -> float:
        """Get audio duration using pydub."""
        try:
            from pydub import AudioSegment

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
