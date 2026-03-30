from __future__ import annotations

from pathlib import Path

from src.utils.models import GeneratedScript, NicheConfig, Platform
from src.voice_generator.voice import VoiceGenerator


def _sample_script() -> GeneratedScript:
    return GeneratedScript(
        trend_topic="Test Topic",
        niche="technology",
        platform=Platform.YOUTUBE,
        full_text="Hello world",
    )


def _sample_niche(voice: str) -> NicheConfig:
    return NicheConfig(
        name="technology",
        display_name="Tech",
        description="Tech niche",
        tts_voice=voice,
    )


def test_build_voice_retry_order_prioritizes_niche_and_deduplicates() -> None:
    generator = VoiceGenerator()
    niche = _sample_niche("en-US-AriaNeural")

    order = generator._build_voice_retry_order(niche)

    assert order[0] == "en-US-AriaNeural"
    assert len(order) == len(set(order))


def test_generate_uses_niche_voice_first(tmp_path: Path) -> None:
    generator = VoiceGenerator()
    script = _sample_script()
    niche = _sample_niche("en-US-AriaNeural")
    attempted_voices: list[str] = []

    async def fake_generate_async(text: str, voice: str, output_path: Path) -> float:
        attempted_voices.append(voice)
        output_path.write_bytes(b"x" * 2000)
        return 1.25

    generator._generate_async = fake_generate_async  # type: ignore[method-assign]

    result = generator.generate(script, niche)

    assert result.voice_id == "en-US-AriaNeural"
    assert attempted_voices[0] == "en-US-AriaNeural"
