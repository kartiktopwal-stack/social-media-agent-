"""Main execution pipeline for automated Instagram posting."""

from __future__ import annotations

import os

import requests
from dotenv import load_dotenv

from src.ai.groq_client import generate_caption
from src.publishers.instagram_publisher import post_image

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"
REQUEST_TIMEOUT_SECONDS = 10


def get_trending_topic() -> str:
    """Return a placeholder trending topic."""
    return "AI is transforming student life"


def fetch_pexels_image(query: str) -> str:
    """Fetch the first matching image URL from Pexels for a query."""
    pexels_api_key = os.getenv("PEXELS_API_KEY", "").strip()
    if not pexels_api_key:
        raise ValueError("Missing PEXELS_API_KEY environment variable")

    params = {"query": query, "per_page": 1, "page": 1}
    headers = {"Authorization": pexels_api_key}

    response = requests.get(
        PEXELS_SEARCH_URL,
        headers=headers,
        params=params,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    payload = response.json()
    photos = payload.get("photos", [])
    if not photos:
        raise ValueError(f"No images found on Pexels for query: {query}")

    image_url = str(photos[0].get("src", {}).get("large2x", "")).strip()
    if not image_url:
        raise ValueError("Pexels response missing image URL")

    return image_url


def run_pipeline() -> None:
    """Run end-to-end topic, caption, image, and Instagram post pipeline."""
    try:
        topic = get_trending_topic()
        print(f"Topic: {topic}")

        caption = generate_caption(topic)
        print(f"Caption: {caption}")

        image_url = fetch_pexels_image(topic)
        print(f"Image URL: {image_url}")

        post_id = post_image(image_url, caption)
        print(f"Post ID: {post_id}")
    except Exception as exc:
        print(f"Pipeline failed: {exc}")


if __name__ == "__main__":
    load_dotenv()
    run_pipeline()
