"""
src/trend_engine/collector.py
─────────────────────────────────────────────────────────────────────────────
Trend Finder Agent — Collects trending topics from multiple sources
and scores them for virality using AI.

Sources: Google Trends, Reddit, NewsAPI, HackerNews, YouTube
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

import httpx
from tenacity import RetryError, retry, stop_after_attempt, wait_exponential

from config.settings import settings
from src.core.db import get_keyword_index, set_keyword_index
from src.core.exceptions import TrendCollectionError
from src.utils.logger import get_logger
from src.utils.models import NicheConfig, RawTrend, ScoredTrend, TrendSource

logger = get_logger("trend_engine")

YOUTUBE_ALLOWED_LANGUAGES = {"en", "en-us", "en-gb"}
YOUTUBE_MAX_SOURCE_DURATION_SECONDS = 3600


class TrendCollector:
    """Base class for individual trend source collectors."""

    source: TrendSource

    def __init__(self) -> None:
        self._client = httpx.Client(timeout=30.0)

    @retry(
        stop=stop_after_attempt(settings.max_retry_attempts),
        wait=wait_exponential(
            multiplier=settings.retry_backoff_seconds,
            min=settings.retry_backoff_seconds,
            max=max(settings.retry_backoff_seconds * 8, settings.retry_backoff_seconds),
        ),
    )
    def _request_json(self, url: str, params: dict | None = None) -> dict | list:
        """Perform an HTTP request with retry and return JSON payload."""
        response = self._client.get(url, params=params)
        # Eagerly read the full body so it is available on HTTPStatusError.response
        # even after the response stream is closed.
        response.read()
        response.raise_for_status()
        return response.json()

    def collect(self, niche: NicheConfig) -> list[RawTrend]:
        raise NotImplementedError

    def close(self) -> None:
        self._client.close()


class GoogleTrendsCollector(TrendCollector):
    """Collect trending topics from Google Trends via SerpAPI."""

    source = TrendSource.GOOGLE_TRENDS
    SERPAPI_BASE = "https://serpapi.com/search"

    @staticmethod
    def _log_serpapi_error(event: str, exc: Exception) -> None:
        """Log the full HTTP status code + response body from a SerpAPI failure.

        Handles both direct httpx.HTTPStatusError and tenacity.RetryError
        (which wraps the real error after all retries are exhausted).
        """
        original: BaseException | None = exc

        # Unwrap RetryError → get the real exception from the last attempt
        if isinstance(exc, RetryError):
            last = exc.last_attempt
            if last is not None:
                try:
                    original = last.exception()
                except Exception:
                    original = None

        if isinstance(original, httpx.HTTPStatusError):
            resp = original.response
            logger.warning(
                event,
                status_code=resp.status_code,
                response_body=resp.text[:2000],
                request_url=str(original.request.url),
                error=str(original),
            )
        else:
            # Fall back to a generic log with whatever string info is available
            logger.warning(event, error=str(exc))

    def collect(self, niche: NicheConfig) -> list[RawTrend]:
        logger.info("collecting_google_trends", niche=niche.name)
        trends: list[RawTrend] = []

        if not settings.serpapi_key:
            logger.warning("serpapi_not_configured")
            return trends

        # Send one keyword per request — SerpAPI rejects comma-separated
        # multi-keyword queries with a 400 error.
        keywords = niche.keywords[:5] if niche.keywords else [niche.display_name]

        for keyword in keywords:
            try:
                trends.extend(self._fetch_related_queries(keyword))
            except Exception as e:
                self._log_serpapi_error("google_trends_collection_failed", e)

            try:
                trends.extend(self._fetch_related_topics(keyword))
            except Exception as e:
                self._log_serpapi_error("google_trends_collection_failed", e)

        logger.info("google_trends_collected", count=len(trends))
        return trends

    def _fetch_related_queries(self, query: str) -> list[RawTrend]:
        """Fetch rising related queries from SerpAPI Google Trends."""
        trends: list[RawTrend] = []
        try:
            data = self._request_json(
                self.SERPAPI_BASE,
                {
                    "engine": "google_trends",
                    "q": query,
                    "data_type": "RELATED_QUERIES",
                    "geo": "US",
                    "hl": "en",
                    "api_key": settings.serpapi_key,
                },
            )
            logger.debug("serpapi_raw_response", data_type="RELATED_QUERIES", query=query, data=data)

            for item in data.get("related_queries", {}).get("rising", [])[:10]:
                topic = item.get("query", "")
                if topic:
                    # SerpAPI returns value like "Breakout" or a percentage
                    raw_value = str(item.get("value", "0"))
                    pop_score = self._parse_popularity(raw_value)
                    trends.append(
                        RawTrend(
                            topic=topic,
                            source=self.source,
                            url=item.get("serpapi_link", ""),
                            description=f"Rising query on Google Trends: {topic}",
                            popularity_score=pop_score,
                        )
                    )

        except Exception as e:
            self._log_serpapi_error("serpapi_related_queries_failed", e)

        return trends

    def _fetch_related_topics(self, query: str) -> list[RawTrend]:
        """Fetch rising related topics from SerpAPI Google Trends."""
        trends: list[RawTrend] = []
        try:
            data = self._request_json(
                self.SERPAPI_BASE,
                {
                    "engine": "google_trends",
                    "q": query,
                    "data_type": "RELATED_TOPICS",
                    "geo": "US",
                    "hl": "en",
                    "api_key": settings.serpapi_key,
                },
            )
            logger.debug("serpapi_raw_response", data_type="RELATED_TOPICS", query=query, data=data)

            for item in data.get("related_topics", {}).get("rising", [])[:10]:
                topic_title = item.get("topic", {}).get("title", "")
                if not topic_title:
                    continue
                raw_value = str(item.get("value", "0"))
                pop_score = self._parse_popularity(raw_value)
                trends.append(
                    RawTrend(
                        topic=topic_title,
                        source=self.source,
                        url=item.get("serpapi_link", ""),
                        description=f"Rising topic on Google Trends: {topic_title}",
                        popularity_score=pop_score,
                    )
                )

        except Exception as e:
            self._log_serpapi_error("serpapi_related_topics_failed", e)

        return trends

    @staticmethod
    def _parse_popularity(raw_value: str) -> float:
        """Convert SerpAPI trend value to a 0-10 score.

        Values can be:
        - "Breakout" → very high interest → 10.0
        - A percentage string like "+900%" → scaled 0-10
        - A plain integer string
        """
        v = raw_value.strip()
        if v.lower() == "breakout":
            return 10.0
        # Strip +, %, commas
        v = v.replace("+", "").replace("%", "").replace(",", "")
        try:
            num = float(v)
            # Percentage values: 0..5000+ → scale to 0..10
            return min(num / 500, 10.0)
        except ValueError:
            return 5.0


class RedditCollector(TrendCollector):
    """Collect rising/hot posts from Reddit based on niche keywords and subreddits."""

    source = TrendSource.REDDIT

    def collect(self, niche: NicheConfig) -> list[RawTrend]:
        logger.info("collecting_reddit_trends", niche=niche.name)
        trends: list[RawTrend] = []

        if not settings.reddit_client_id or not settings.reddit_client_secret:
            logger.warning("reddit_not_configured")
            return trends

        try:
            import praw

            reddit = praw.Reddit(
                client_id=settings.reddit_client_id,
                client_secret=settings.reddit_client_secret,
                user_agent=settings.reddit_user_agent,
            )

            # 1. Fetch from configured subreddits (hot + rising)
            if niche.subreddits:
                trends.extend(self._collect_from_subreddits(reddit, niche.subreddits[:3]))

            # 2. Search Reddit by niche keywords for broader coverage
            if niche.keywords:
                trends.extend(self._search_by_keywords(reddit, niche.keywords[:5]))

            # 3. If nothing configured, search with the niche display name
            if not niche.subreddits and not niche.keywords:
                trends.extend(self._search_by_keywords(reddit, [niche.display_name]))

        except Exception as e:
            logger.warning("reddit_collection_failed", error=str(e))

        logger.info("reddit_trends_collected", count=len(trends))
        return trends

    def _collect_from_subreddits(
        self, reddit, subreddits: list[str]
    ) -> list[RawTrend]:
        """Fetch hot and rising posts from specific subreddits."""
        trends: list[RawTrend] = []

        for sub_name in subreddits:
            try:
                subreddit = reddit.subreddit(sub_name)

                # Hot posts — high engagement, currently popular
                for post in subreddit.hot(limit=10):
                    if post.stickied:
                        continue
                    trends.append(self._post_to_raw_trend(post))

                # Rising posts — gaining momentum right now
                for post in subreddit.rising(limit=10):
                    if post.stickied:
                        continue
                    trends.append(self._post_to_raw_trend(post, rising_bonus=2.0))

            except Exception as e:
                logger.warning("reddit_subreddit_failed", subreddit=sub_name, error=str(e))

        return trends

    def _search_by_keywords(
        self, reddit, keywords: list[str]
    ) -> list[RawTrend]:
        """Search Reddit across all subreddits for niche-relevant trending posts."""
        trends: list[RawTrend] = []

        for keyword in keywords:
            try:
                # Search for recent, high-relevance posts
                for post in reddit.subreddit("all").search(
                    keyword, sort="hot", time_filter="day", limit=10
                ):
                    if post.stickied:
                        continue
                    trends.append(self._post_to_raw_trend(post))
            except Exception as e:
                logger.warning(
                    "reddit_keyword_search_failed",
                    keyword=keyword,
                    error=str(e),
                )

        return trends

    def _post_to_raw_trend(self, post, rising_bonus: float = 0.0) -> RawTrend:
        """Convert a PRAW submission to a RawTrend."""
        # Score formula: upvotes/1000 capped at 10, plus bonus for rising posts
        base_score = min(post.score / 1000, 8.0)
        # Upvote ratio boosts genuinely popular content (>0.9 = strong consensus)
        ratio_bonus = max(0, (post.upvote_ratio - 0.7)) * 3.0
        final_score = min(base_score + ratio_bonus + rising_bonus, 10.0)

        return RawTrend(
            topic=post.title,
            source=self.source,
            url=f"https://reddit.com{post.permalink}",
            description=post.selftext[:200] if post.selftext else "",
            popularity_score=final_score,
        )


class NewsAPICollector(TrendCollector):
    """Collect top headlines from NewsAPI."""

    source = TrendSource.NEWSAPI

    def collect(self, niche: NicheConfig) -> list[RawTrend]:
        logger.info("collecting_newsapi_trends", niche=niche.name)
        trends: list[RawTrend] = []

        if not settings.news_api_key:
            logger.warning("newsapi_not_configured")
            return trends

        try:
            data = self._request_json(
                "https://newsapi.org/v2/top-headlines",
                {
                    "category": niche.news_category,
                    "language": "en",
                    "pageSize": 10,
                    "apiKey": settings.news_api_key,
                },
            )

            for article in data.get("articles", []):
                title = article.get("title", "")
                if title and title != "[Removed]":
                    trends.append(
                        RawTrend(
                            topic=title,
                            source=self.source,
                            url=article.get("url", ""),
                            description=article.get("description", "") or "",
                            popularity_score=6.0,
                        )
                    )

        except Exception as e:
            logger.warning("newsapi_collection_failed", error=str(e))

        logger.info("newsapi_trends_collected", count=len(trends))
        return trends


class HackerNewsCollector(TrendCollector):
    """Collect top stories from Hacker News."""

    source = TrendSource.HACKERNEWS

    def collect(self, niche: NicheConfig) -> list[RawTrend]:
        logger.info("collecting_hackernews_trends", niche=niche.name)
        trends: list[RawTrend] = []

        try:
            story_ids = self._request_json(
                "https://hacker-news.firebaseio.com/v0/topstories.json"
            )[:15]

            for story_id in story_ids:
                try:
                    story = self._request_json(
                        f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
                    )

                    if story and story.get("title"):
                        trends.append(
                            RawTrend(
                                topic=story["title"],
                                source=self.source,
                                url=story.get("url", f"https://news.ycombinator.com/item?id={story_id}"),
                                description="",
                                popularity_score=min(story.get("score", 0) / 100, 10.0),
                            )
                        )
                except Exception as e:
                    logger.debug("hn_story_fetch_failed", story_id=story_id, error=str(e))

        except Exception as e:
            logger.warning("hackernews_collection_failed", error=str(e))

        logger.info("hackernews_trends_collected", count=len(trends))
        return trends


class YouTubeTrendCollector(TrendCollector):
    """Collect trending videos from YouTube Data API."""

    source = TrendSource.YOUTUBE
    _MIN_DURATION_SECONDS = 180
    _DURATION_RE = re.compile(
        r"^P"
        r"(?:(?P<days>\d+)D)?"
        r"(?:T"
        r"(?:(?P<hours>\d+)H)?"
        r"(?:(?P<minutes>\d+)M)?"
        r"(?:(?P<seconds>\d+)S)?"
        r")?$"
    )

    def collect(self, niche: NicheConfig) -> list[RawTrend]:
        logger.info("collecting_youtube_trends", niche=niche.name)
        trends: list[RawTrend] = []

        if not settings.youtube_api_key:
            logger.warning("youtube_api_not_configured")
            return trends

        try:
            published_after = (
                datetime.now(timezone.utc) - timedelta(hours=48)
            ).replace(microsecond=0).isoformat().replace("+00:00", "Z")

            search_params = {
                "part": "id",
                "type": "video",
                "order": "viewCount",
                "publishedAfter": published_after,
                "maxResults": 25,
                "regionCode": "US",
                "key": settings.youtube_api_key,
            }
            if niche.youtube_category_id:
                search_params["videoCategoryId"] = niche.youtube_category_id

            search_query = self._build_search_query(niche)
            if search_query:
                search_params["q"] = search_query

            search_data = self._request_json(
                "https://www.googleapis.com/youtube/v3/search",
                search_params,
            )

            video_ids = self._extract_video_ids(search_data.get("items", []))
            if not video_ids:
                logger.info("youtube_search_returned_no_videos", niche=niche.name)
                logger.info("youtube_trends_collected", count=0)
                return trends

            data = self._request_json(
                "https://www.googleapis.com/youtube/v3/videos",
                {
                    "part": "snippet,statistics,contentDetails",
                    "id": ",".join(video_ids[:25]),
                    "key": settings.youtube_api_key,
                },
            )

            for item in data.get("items", []):
                snippet = item.get("snippet", {})
                stats = item.get("statistics", {})
                duration_text = item.get("contentDetails", {}).get("duration", "")
                duration_seconds = self._parse_duration_seconds(duration_text)

                if duration_seconds < self._MIN_DURATION_SECONDS:
                    logger.info(
                        "skipping_short_youtube_video",
                        video_id=item.get("id", ""),
                        duration=duration_text,
                        duration_seconds=duration_seconds,
                    )
                    continue

                if duration_seconds > YOUTUBE_MAX_SOURCE_DURATION_SECONDS:
                    logger.warning(
                        "skipping_long_youtube_video",
                        video_id=item.get("id", ""),
                        duration=duration_text,
                        duration_seconds=duration_seconds,
                    )
                    continue

                language = snippet.get("defaultAudioLanguage") or snippet.get("defaultLanguage")
                language_key = language.strip().lower() if isinstance(language, str) else ""
                if language_key and language_key not in YOUTUBE_ALLOWED_LANGUAGES:
                    logger.warning(
                        "skipping_non_english_youtube_video",
                        video_id=item.get("id", ""),
                        language=language,
                    )
                    continue

                trends.append(
                    RawTrend(
                        topic=snippet.get("title", ""),
                        source=self.source,
                        url=f"https://youtube.com/watch?v={item['id']}",
                        description=snippet.get("description", "")[:200],
                        popularity_score=min(int(stats.get("viewCount", 0)) / 100000, 10.0),
                    )
                )

        except Exception as e:
            logger.warning("youtube_trend_collection_failed", error=str(e))

        logger.info("youtube_trends_collected", count=len(trends))
        return trends

    @staticmethod
    def _build_search_query(niche: NicheConfig) -> str:
        """Rotate through niche keywords to keep search results niche-specific."""
        keywords = [keyword.strip() for keyword in niche.keywords if keyword.strip()]
        if not keywords:
            return ""

        if len(keywords) == 1:
            return keywords[0]

        index = get_keyword_index(niche.name)
        keyword = keywords[index % len(keywords)]
        next_index = (index + 1) % len(keywords)
        set_keyword_index(niche.name, next_index)
        return keyword

    @staticmethod
    def _extract_video_ids(items: list[dict]) -> list[str]:
        """Extract unique video IDs from a YouTube search response."""
        video_ids: list[str] = []
        seen: set[str] = set()
        for item in items:
            video_id = item.get("id", {}).get("videoId", "")
            if not video_id or video_id in seen:
                continue
            seen.add(video_id)
            video_ids.append(video_id)
        return video_ids

    @classmethod
    def _parse_duration_seconds(cls, duration_text: str) -> int:
        """Parse an ISO 8601 YouTube duration (e.g. PT15M33S) into seconds."""
        if not duration_text:
            return 0

        match = cls._DURATION_RE.match(duration_text)
        if not match:
            logger.warning("youtube_duration_parse_failed", duration=duration_text)
            return 0

        parts = {name: int(value or 0) for name, value in match.groupdict().items()}
        return (
            parts["days"] * 86400
            + parts["hours"] * 3600
            + parts["minutes"] * 60
            + parts["seconds"]
        )


class ViralityScorer:
    """Score trends for virality potential using AI (Groq / Llama)."""

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def score(self, trends: list[RawTrend], niche: NicheConfig) -> list[ScoredTrend]:
        logger.info("scoring_virality", count=len(trends), niche=niche.name)

        if not trends:
            return []

        if not settings.groq_api_key:
            logger.warning("groq_not_configured_using_heuristic")
            return self._heuristic_score(trends, niche)

        try:
            from groq import Groq

            client = Groq(api_key=settings.groq_api_key)

            topics_text = "\n".join(
                f"- {t.topic} (source: {t.source.value}, popularity: {t.popularity_score:.1f})"
                for t in trends[:20]
            )

            prompt = f"""You are a social media virality expert for the "{niche.display_name}" niche.

Analyze these trending topics and score each for short-form video virality potential (1-10):

{topics_text}

For each topic, return a JSON array with objects containing:
- "topic": the topic text
- "score": virality score 1-10
- "reasoning": brief explanation (1 sentence)
- "keywords": list of 3-5 video keywords

Return ONLY valid JSON array, no other text."""

            response = client.chat.completions.create(
                model=settings.ai_model,
                messages=[{"role": "user", "content": prompt}],
            )
            text = (response.choices[0].message.content or "").strip()

            # Extract JSON from response
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            scored_data = json.loads(text)

            scored: list[ScoredTrend] = []
            for item in scored_data:
                scored.append(
                    ScoredTrend(
                        niche=niche.name,
                        topic=item.get("topic", ""),
                        virality_score=float(item.get("score", 5.0)),
                        reasoning=item.get("reasoning", ""),
                        keywords=item.get("keywords", []),
                        sources=[t.source.value for t in trends if t.topic == item.get("topic", "")][:2],
                    )
                )

            scored.sort(key=lambda x: x.virality_score, reverse=True)
            logger.info("virality_scoring_complete", scored_count=len(scored))
            return scored

        except Exception as e:
            logger.error("ai_scoring_failed", error=str(e))
            return self._heuristic_score(trends, niche)

    def _heuristic_score(self, trends: list[RawTrend], niche: NicheConfig) -> list[ScoredTrend]:
        """Fallback scoring without AI."""
        scored: list[ScoredTrend] = []
        for trend in trends:
            keyword_bonus = sum(
                1.0 for kw in niche.keywords if kw.lower() in trend.topic.lower()
            )
            score = min(trend.popularity_score + keyword_bonus, 10.0)
            scored.append(
                ScoredTrend(
                    niche=niche.name,
                    topic=trend.topic,
                    description=trend.description,
                    virality_score=score,
                    reasoning="Heuristic scoring (AI unavailable)",
                    sources=[trend.source.value],
                )
            )
        scored.sort(key=lambda x: x.virality_score, reverse=True)
        return scored


class TrendAggregator:
    """Orchestrates all trend collectors and scoring."""

    def __init__(self) -> None:
        self._collectors: list[TrendCollector] = [
            GoogleTrendsCollector(),
            RedditCollector(),
            NewsAPICollector(),
            HackerNewsCollector(),
            YouTubeTrendCollector(),
        ]
        self._scorer = ViralityScorer()

    def run(self, niche: NicheConfig) -> list[ScoredTrend]:
        """Collect from all sources, deduplicate, and score."""
        logger.info("trend_aggregation_start", niche=niche.name)

        all_trends: list[RawTrend] = []
        for collector in self._collectors:
            try:
                trends = collector.collect(niche)
                all_trends.extend(trends)
                logger.info(
                    "source_collected",
                    source=collector.source.value,
                    count=len(trends),
                )
            except Exception as e:
                logger.error(
                    "collector_failed",
                    source=collector.source.value,
                    error=str(e),
                )

        if not all_trends:
            fallback_trends = self._fallback_trends(niche)
            if fallback_trends:
                logger.warning(
                    "no_trends_collected_using_fallback",
                    niche=niche.name,
                    fallback_count=len(fallback_trends),
                )
                all_trends.extend(fallback_trends)
            else:
                logger.warning("no_trends_collected", niche=niche.name)
                raise TrendCollectionError(f"No trends found for niche '{niche.name}'")

        # Deduplicate by topic similarity
        seen: set[str] = set()
        unique: list[RawTrend] = []
        for trend in all_trends:
            key = trend.topic.lower().strip()[:50]
            if key not in seen:
                seen.add(key)
                unique.append(trend)

        logger.info("trends_deduplicated", total=len(all_trends), unique=len(unique))

        scored = self._scorer.score(unique, niche)
        logger.info(
            "trend_aggregation_complete",
            niche=niche.name,
            scored_count=len(scored),
            top_score=scored[0].virality_score if scored else 0,
        )
        return scored

    def close(self) -> None:
        for c in self._collectors:
            c.close()

    @staticmethod
    def _fallback_trends(niche: NicheConfig) -> list[RawTrend]:
        """Create safe fallback trends so dry-run can proceed without external APIs."""
        seed_topics = niche.keywords[:5] or [niche.display_name, niche.name]
        fallback_topics = [f"{topic.title()} update" for topic in seed_topics if topic]
        return [
            RawTrend(
                topic=topic,
                source=TrendSource.NEWSAPI,
                description=f"Fallback trend generated for niche '{niche.name}'",
                popularity_score=4.0,
            )
            for topic in fallback_topics
        ]
