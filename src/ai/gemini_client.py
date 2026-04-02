"""Gemini client helpers for social media content generation."""

from __future__ import annotations

import os
from typing import Any

from google import genai
from google.genai import errors as genai_errors

MODEL_NAME = "gemini-2.5-flash"


class GeminiClientError(RuntimeError):
    """Raised when Gemini content generation fails."""


def _get_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise GeminiClientError("Missing GEMINI_API_KEY environment variable")
    return genai.Client(api_key=api_key)


def _response_text(response: Any) -> str:
    text = str(getattr(response, "text", "")).strip()
    if not text:
        raise GeminiClientError("Gemini returned an empty response")
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
        response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
        return " ".join(_response_text(response).split())
    except (genai_errors.APIError, genai_errors.ClientError) as exc:
        raise GeminiClientError(f"Gemini API request failed: {exc}") from exc
    except Exception as exc:
        raise GeminiClientError(f"Caption generation failed: {exc}") from exc


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
        response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
        ideas = [line.strip(" -•\t") for line in _response_text(response).splitlines() if line.strip()]

        if not ideas:
            raise GeminiClientError("No post ideas were generated")

        return list(dict.fromkeys(ideas))
    except (genai_errors.APIError, genai_errors.ClientError) as exc:
        raise GeminiClientError(f"Gemini API request failed: {exc}") from exc
    except Exception as exc:
        raise GeminiClientError(f"Post idea generation failed: {exc}") from exc
