"""
src/script_generator/generator.py
─────────────────────────────────────────────────────────────────────────────
Script Writer Agent — Generates optimized short-form video scripts
using AI (Groq / Llama), structured as HOOK + BODY + CTA.
"""

from __future__ import annotations

import json
import os
import re

from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings
from src.core.exceptions import ScriptGenerationError
from src.utils.logger import get_logger
from src.utils.models import (
    GeneratedScript,
    NicheConfig,
    Platform,
    ScoredTrend,
    ScriptSections,
)

logger = get_logger("script_generator")

# Average speaking rate for duration estimates
WORDS_PER_SECOND = 2.5


class ScriptGenerator:
    """Generate short-form video scripts using AI."""

    STYLE_PROMPTS = {
        "dramatic_reveal": (
            "Start with a shocking statement or question that stops scrolling. "
            "Build tension through the body. End with a mind-blowing reveal or call to action."
        ),
        "breaking_news": (
            "Open with BREAKING urgency. Present facts rapidly. "
            "Close with what this means for the viewer."
        ),
        "storytelling": (
            "Begin with 'You won't believe...' or similar hook. "
            "Tell the story with emotional beats. End with an unexpected twist."
        ),
        "educational": (
            "Start with a surprising fact. Explain in simple terms. "
            "End with a practical takeaway the viewer can use today."
        ),
        "listicle": (
            "Open with the number of items and why they matter. "
            "Present each item briefly. End with the most impressive one."
        ),
    }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def generate(
        self,
        trend: ScoredTrend,
        niche: NicheConfig,
        platform: Platform,
    ) -> GeneratedScript:
        """Generate a complete video script for the given trend."""
        logger.info(
            "generating_script",
            topic=trend.topic,
            niche=niche.name,
            platform=platform.value,
        )

        if not settings.groq_api_key:
            logger.warning("groq_not_configured_generating_template")
            return self._generate_template(trend, niche, platform)

        try:
            from groq import Groq

            client = Groq(api_key=settings.groq_api_key)

            style_guide = self.STYLE_PROMPTS.get(niche.script_style, self.STYLE_PROMPTS["dramatic_reveal"])

            prompt = f"""You are an expert short-form video scriptwriter for the "{niche.display_name}" niche.

TOPIC: {trend.topic}
PLATFORM: {platform.value}
TONE: {niche.tone}
STYLE: {style_guide}

Write a 60-second video script (approximately 150 words) with this EXACT JSON structure:
{{
    "title": "Catchy video title (max 100 chars, with emoji)",
    "description": "YouTube/social description (2-3 sentences with keywords)",
    "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
    "hook": "Opening 1-2 sentences that STOP the scroll (max 20 words)",
    "body": [
        "First key point or fact (1-2 sentences)",
        "Second key point with detail (1-2 sentences)",
        "Third key point or escalation (1-2 sentences)",
        "Fourth key point or climax (1-2 sentences)"
    ],
    "cta": "Strong call to action (follow, like, comment prompt)"
}}

Rules:
- Hook MUST be shocking, controversial, or curiosity-inducing
- Each body point should be a standalone compelling statement
- Use simple, conversational language (grade 6-8 reading level)
- Include natural pauses with "..." or em dashes
- Total script should be under 160 words for a 60-second video
- Tags should be relevant trending keywords

Return ONLY valid JSON, no other text."""

            response = client.chat.completions.create(
                model=settings.ai_model,
                messages=[{"role": "user", "content": prompt}],
            )
            text = (response.choices[0].message.content or "").strip()

            # Extract JSON
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            data = json.loads(text)

            sections = ScriptSections(
                hook=data.get("hook", ""),
                body=data.get("body", []),
                cta=data.get("cta", ""),
            )

            full_text = self._build_full_text(sections)
            word_count = len(full_text.split())

            script = GeneratedScript(
                trend_topic=trend.topic,
                niche=niche.name,
                platform=platform,
                title=data.get("title", trend.topic),
                description=data.get("description", ""),
                tags=data.get("tags", []),
                sections=sections,
                full_text=full_text,
                word_count=word_count,
                estimated_duration_s=word_count / WORDS_PER_SECOND,
            )

            logger.info(
                "script_generated",
                topic=trend.topic,
                words=word_count,
                duration_s=script.estimated_duration_s,
            )
            return script

        except json.JSONDecodeError as e:
            logger.error("script_json_parse_failed", error=str(e))
            raise ScriptGenerationError(f"Failed to parse AI script response: {e}")
        except Exception as e:
            logger.error("script_generation_failed", error=str(e))
            raise ScriptGenerationError(str(e))

    def _generate_template(
        self,
        trend: ScoredTrend,
        niche: NicheConfig,
        platform: Platform,
    ) -> GeneratedScript:
        """Generate a template script when AI is unavailable."""
        sections = ScriptSections(
            hook=f"Did you know this about {trend.topic}? Here's what everyone's missing...",
            body=[
                f"{trend.topic} is taking the world by storm right now.",
                f"Experts in {niche.display_name} are calling this a game-changer.",
                "Here's the part that will blow your mind...",
                f"This could change everything we know about {niche.display_name.lower()}.",
            ],
            cta="Follow for more mind-blowing updates! Drop a comment below!",
        )
        full_text = self._build_full_text(sections)
        word_count = len(full_text.split())

        return GeneratedScript(
            trend_topic=trend.topic,
            niche=niche.name,
            platform=platform,
            title=f"{trend.topic} - What They Don't Want You to Know",
            description=f"Latest on {trend.topic} in {niche.display_name}. #shorts #trending",
            tags=[niche.name, "trending", "viral", "shorts"],
            sections=sections,
            full_text=full_text,
            word_count=word_count,
            estimated_duration_s=word_count / WORDS_PER_SECOND,
        )

    @staticmethod
    def _build_full_text(sections: ScriptSections) -> str:
        parts = [sections.hook]
        parts.extend(sections.body)
        parts.append(sections.cta)
        return " ".join(parts)
