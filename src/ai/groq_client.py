"""Groq client helpers for social media content generation."""

from __future__ import annotations

import os
from typing import Any

from groq import Groq

MODEL_NAME = "llama-3.3-70b-versatile"


class GroqClientError(RuntimeError):
    """Raised when Groq content generation fails."""


def _get_client() -> Groq:
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise GroqClientError("Missing GROQ_API_KEY environment variable")
    return Groq(api_key=api_key)


def _response_text(response: Any) -> str:
    text = (response.choices[0].message.content or "").strip()
    if not text:
        raise GroqClientError("Groq returned an empty response")
    return text


def generate_caption(topic: str) -> str:
    topic_clean = topic.strip()
    if not topic_clean:
        raise ValueError("topic must be a non-empty string")

    prompt = (
        "Write one high-performing social media caption for this topic. "
        "Requirements: 1-2 short sentences, clear hook, no hashtags, no emojis. "
        f"Topic: {topic_clean}"
    )

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
        )
        return " ".join(_response_text(response).split())
    except GroqClientError:
        raise
    except Exception as exc:
        raise GroqClientError(f"Caption generation failed: {exc}") from exc


def generate_post_ideas(niche: str) -> list[str]:
    niche_clean = niche.strip()
    if not niche_clean:
        raise ValueError("niche must be a non-empty string")

    prompt = (
        "Generate exactly 10 unique social media post ideas for this niche. "
        "Return each idea on its own line without numbering. "
        f"Niche: {niche_clean}"
    )

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
        )
        ideas = [line.strip(" -•\t") for line in _response_text(response).splitlines() if line.strip()]

        if not ideas:
            raise GroqClientError("No post ideas were generated")

        return list(dict.fromkeys(ideas))
    except GroqClientError:
        raise
    except Exception as exc:
        raise GroqClientError(f"Post idea generation failed: {exc}") from exc
