"""Instagram publisher using the Meta Graph API."""

from __future__ import annotations

import os
from typing import Any

import requests
from dotenv import load_dotenv


load_dotenv()


class InstagramPublishError(Exception):
    """Raised when Instagram publishing fails."""


META_GRAPH_BASE_URL = "https://graph.facebook.com/v19.0"
REQUEST_TIMEOUT_SECONDS = 10


def _validate_env() -> tuple[str, str]:
    """Validate required environment variables for Instagram publishing."""
    meta_access_token = os.getenv("META_ACCESS_TOKEN", "").strip()
    instagram_user_id = os.getenv("INSTAGRAM_USER_ID", "").strip()

    missing_vars: list[str] = []
    if not meta_access_token:
        missing_vars.append("META_ACCESS_TOKEN")
    if not instagram_user_id:
        missing_vars.append("INSTAGRAM_USER_ID")

    if missing_vars:
        raise InstagramPublishError(
            f"Missing required environment variable(s): {', '.join(missing_vars)}"
        )

    return meta_access_token, instagram_user_id


def _ensure_success(response: requests.Response, action: str) -> dict[str, Any]:
    """Validate API response and return parsed JSON payload."""
    if response.status_code >= 400:
        raise InstagramPublishError(
            f"Instagram API error during {action} "
            f"(status={response.status_code}): {response.text}"
        )

    try:
        return response.json()
    except ValueError as exc:
        raise InstagramPublishError(
            f"Invalid JSON response during {action}: {response.text}"
        ) from exc


def create_image_container(image_url: str, caption: str) -> str:
    """Create an Instagram media container and return its ID."""
    meta_access_token, instagram_user_id = _validate_env()

    endpoint = f"{META_GRAPH_BASE_URL}/{instagram_user_id}/media"
    payload = {
        "image_url": image_url,
        "caption": caption,
        "access_token": meta_access_token,
    }

    response = requests.post(endpoint, data=payload, timeout=REQUEST_TIMEOUT_SECONDS)
    data = _ensure_success(response, "create_image_container")

    container_id = str(data.get("id", "")).strip()
    if not container_id:
        raise InstagramPublishError(
            f"Instagram API did not return container id: {response.text}"
        )

    print(f"[Instagram] Container created: {container_id}")
    return container_id


def publish_container(container_id: str) -> str:
    """Publish an Instagram media container and return the post ID."""
    meta_access_token, instagram_user_id = _validate_env()

    endpoint = f"{META_GRAPH_BASE_URL}/{instagram_user_id}/media_publish"
    payload = {
        "creation_id": container_id,
        "access_token": meta_access_token,
    }

    response = requests.post(endpoint, data=payload, timeout=REQUEST_TIMEOUT_SECONDS)
    data = _ensure_success(response, "publish_container")

    post_id = str(data.get("id", "")).strip()
    if not post_id:
        raise InstagramPublishError(
            f"Instagram API did not return post id: {response.text}"
        )

    print(f"[Instagram] Post published: {post_id}")
    return post_id


def post_image(image_url: str, caption: str) -> str:
    """Create and publish an Instagram image post in one flow."""
    _validate_env()
    print("[Instagram] Starting image post...")

    container_id = create_image_container(image_url=image_url, caption=caption)
    print(f"[Instagram] Using container ID: {container_id}")

    post_id = publish_container(container_id=container_id)
    print(f"[Instagram] Final post ID: {post_id}")
    return post_id
