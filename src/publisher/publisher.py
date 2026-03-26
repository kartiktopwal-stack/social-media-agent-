"""
src/publisher/publisher.py
─────────────────────────────────────────────────────────────────────────────
Auto Publisher Agent — Publishes videos to YouTube Shorts, Instagram Reels,
TikTok, and X/Twitter.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings
from src.core.exceptions import PublishingError
from src.utils.logger import get_logger
from src.utils.models import FinalVideo, NicheConfig, Platform, PublishResult

logger = get_logger("publisher")


class BasePublisher:
    """Base class for platform-specific publishers."""

    platform: Platform

    def publish(self, video: FinalVideo, niche: NicheConfig) -> PublishResult:
        raise NotImplementedError

    def _make_result(
        self,
        success: bool = False,
        post_id: str = "",
        post_url: str = "",
        error: str = "",
    ) -> PublishResult:
        return PublishResult(
            platform=self.platform,
            success=success,
            post_id=post_id,
            post_url=post_url,
            error=error,
            published_at=datetime.utcnow() if success else None,
        )


class YouTubePublisher(BasePublisher):
    """Publish to YouTube Shorts via YouTube Data API v3."""

    platform = Platform.YOUTUBE

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=2, min=5, max=30),
    )
    def publish(self, video: FinalVideo, niche: NicheConfig) -> PublishResult:
        logger.info("publishing_youtube", title=video.title)

        if not settings.youtube_client_id or not settings.youtube_client_secret:
            logger.warning("youtube_not_configured")
            return self._make_result(error="YouTube credentials not configured")

        try:
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload
            from google.oauth2.credentials import Credentials

            # Build YouTube service
            # In production, credentials would be loaded from stored OAuth tokens
            creds = Credentials(
                token=None,
                client_id=settings.youtube_client_id,
                client_secret=settings.youtube_client_secret,
            )
            youtube = build("youtube", "v3", credentials=creds)

            body = {
                "snippet": {
                    "title": video.title[:100],
                    "description": video.description,
                    "tags": video.tags[:30],
                    "categoryId": niche.youtube_category_id,
                },
                "status": {
                    "privacyStatus": "public",
                    "selfDeclaredMadeForKids": False,
                    "madeForKids": False,
                },
            }

            media = MediaFileUpload(
                str(video.video_path),
                mimetype="video/mp4",
                resumable=True,
                chunksize=10 * 1024 * 1024,
            )

            request = youtube.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media,
            )

            response = request.execute()
            video_id = response.get("id", "")

            logger.info("youtube_published", video_id=video_id)
            return self._make_result(
                success=True,
                post_id=video_id,
                post_url=f"https://youtube.com/shorts/{video_id}",
            )

        except Exception as e:
            logger.error("youtube_publish_failed", error=str(e))
            return self._make_result(error=str(e))


class InstagramPublisher(BasePublisher):
    """Publish to Instagram Reels via Meta Graph API."""

    platform = Platform.INSTAGRAM

    def publish(self, video: FinalVideo, niche: NicheConfig) -> PublishResult:
        logger.info("publishing_instagram", title=video.title)

        if not settings.meta_app_id:
            logger.warning("instagram_not_configured")
            return self._make_result(error="Instagram/Meta credentials not configured")

        try:
            account_id = niche.platforms.get("instagram", {}).get("account_id", "")
            if not account_id:
                return self._make_result(error="Instagram account_id not configured for this niche")

            # Step 1: Upload video container
            # Step 2: Publish container
            # Note: Full implementation requires uploaded video URL
            logger.info("instagram_publish_placeholder")
            return self._make_result(error="Instagram publishing requires uploaded video URL (use object storage)")

        except Exception as e:
            logger.error("instagram_publish_failed", error=str(e))
            return self._make_result(error=str(e))


class TikTokPublisher(BasePublisher):
    """Publish to TikTok via Content Posting API."""

    platform = Platform.TIKTOK

    def publish(self, video: FinalVideo, niche: NicheConfig) -> PublishResult:
        logger.info("publishing_tiktok", title=video.title)

        if not settings.tiktok_client_key:
            logger.warning("tiktok_not_configured")
            return self._make_result(error="TikTok credentials not configured")

        try:
            # TikTok Content Posting API flow:
            # 1. Initialize upload
            # 2. Upload video chunks
            # 3. Publish
            logger.info("tiktok_publish_placeholder")
            return self._make_result(error="TikTok publishing requires approved app and access tokens")

        except Exception as e:
            logger.error("tiktok_publish_failed", error=str(e))
            return self._make_result(error=str(e))


class TwitterPublisher(BasePublisher):
    """Publish to X/Twitter via API v2."""

    platform = Platform.TWITTER

    def publish(self, video: FinalVideo, niche: NicheConfig) -> PublishResult:
        logger.info("publishing_twitter", title=video.title)

        if not settings.twitter_api_key:
            logger.warning("twitter_not_configured")
            return self._make_result(error="Twitter credentials not configured")

        try:
            import tweepy

            auth = tweepy.OAuth1UserHandler(
                settings.twitter_api_key,
                settings.twitter_api_secret,
                settings.twitter_access_token,
                settings.twitter_access_token_secret,
            )

            api = tweepy.API(auth)
            client = tweepy.Client(
                consumer_key=settings.twitter_api_key,
                consumer_secret=settings.twitter_api_secret,
                access_token=settings.twitter_access_token,
                access_token_secret=settings.twitter_access_token_secret,
            )

            # Upload media
            media = api.media_upload(
                filename=str(video.video_path),
                media_category="tweet_video",
            )

            # Create tweet
            text = f"{video.title}\n\n{' '.join('#' + t for t in video.tags[:5])}"
            if len(text) > 280:
                text = text[:277] + "..."

            response = client.create_tweet(
                text=text,
                media_ids=[media.media_id_string],
            )

            tweet_id = response.data.get("id", "")
            logger.info("twitter_published", tweet_id=tweet_id)
            return self._make_result(
                success=True,
                post_id=tweet_id,
                post_url=f"https://twitter.com/i/status/{tweet_id}",
            )

        except Exception as e:
            logger.error("twitter_publish_failed", error=str(e))
            return self._make_result(error=str(e))


class AutoPublisher:
    """Orchestrates publishing across all configured platforms."""

    def __init__(self) -> None:
        self._publishers: dict[Platform, BasePublisher] = {
            Platform.YOUTUBE: YouTubePublisher(),
            Platform.INSTAGRAM: InstagramPublisher(),
            Platform.TIKTOK: TikTokPublisher(),
            Platform.TWITTER: TwitterPublisher(),
        }

    def publish_all(
        self,
        video: FinalVideo,
        niche: NicheConfig,
        platforms: list[Platform] | None = None,
        dry_run: bool = False,
    ) -> list[PublishResult]:
        """Publish video to all configured platforms."""
        target_platforms = platforms or list(self._publishers.keys())
        results: list[PublishResult] = []

        logger.info(
            "auto_publish_start",
            title=video.title,
            platforms=[p.value for p in target_platforms],
            dry_run=dry_run,
        )

        for platform in target_platforms:
            if dry_run:
                logger.info("dry_run_skip_publish", platform=platform.value)
                results.append(
                    PublishResult(
                        platform=platform,
                        success=True,
                        post_id="dry-run",
                        post_url="",
                        published_at=datetime.utcnow(),
                    )
                )
                continue

            publisher = self._publishers.get(platform)
            if not publisher:
                logger.warning("unknown_platform", platform=platform.value)
                continue

            try:
                result = publisher.publish(video, niche)
                results.append(result)
                if result.success:
                    logger.info(
                        "published",
                        platform=platform.value,
                        post_url=result.post_url,
                    )
                else:
                    logger.warning(
                        "publish_failed",
                        platform=platform.value,
                        error=result.error,
                    )
            except Exception as e:
                logger.error(
                    "publish_error",
                    platform=platform.value,
                    error=str(e),
                )
                results.append(
                    PublishResult(
                        platform=platform,
                        success=False,
                        error=str(e),
                    )
                )

        published = sum(1 for r in results if r.success)
        logger.info(
            "auto_publish_complete",
            total=len(results),
            published=published,
            failed=len(results) - published,
        )
        return results
