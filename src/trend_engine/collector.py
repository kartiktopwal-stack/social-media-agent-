"""
src/trend_engine/collector.py
─────────────────────────────────────────────────────────────────────────────
Trend Finder Agent — Collects trending topics from multiple sources
and scores them for virality using AI.

Sources: Google Trends, Reddit, NewsAPI, HackerNews, YouTube
"""

from __future__ import annotations

import json
from datetime import datetime

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings
from src.core.exceptions import TrendCollectionError
from src.utils.logger import get_logger
from src.utils.models import NicheConfig, RawTrend, ScoredTrend, TrendSource

logger = get_logger("trend_engine")


class TrendCollector:
    """Base class for individual trend source collectors."""

    source: TrendSource

    def __init__(self) -> None:
        self._client = httpx.Client(timeout=30.0)

    def collect(self, niche: NicheConfig) -> list[RawTrend]:
        raise NotImplementedError

    def close(self) -> None:
        self._client.close()


class GoogleTrendsCollector(TrendCollector):
    """Collect trending topics from Google Trends via pytrends."""

    source = TrendSource.GOOGLE_TRENDS

    def collect(self, niche: NicheConfig) -> list[RawTrend]:
        logger.info("collecting_google_trends", niche=niche.name)
        trends: list[RawTrend] = []
        try:
            from pytrends.request import TrendReq

            pytrends = TrendReq(hl="en-US", tz=360)
            # Get trending searches
            trending = pytrends.trending_searches(pn="united_states")
            for _, row in trending.head(10).iterrows():
                topic = str(row[0])
                if any(kw.lower() in topic.lower() for kw in niche.keywords) or not niche.keywords:
                    trends.append(
                        RawTrend(
                            topic=topic,
                            source=self.source,
                            description=f"Trending on Google: {topic}",
                            popularity_score=8.0,
                        )
                    )

            # Also check related topics for niche keywords
            if niche.keywords:
                try:
                    pytrends.build_payload(niche.keywords[:5], timeframe="now 1-d")
                    related = pytrends.related_topics()
                    for kw, data in related.items():
                        if "rising" in data and data["rising"] is not None:
                            for _, row in data["rising"].head(5).iterrows():
                                trends.append(
                                    RawTrend(
                                        topic=str(row.get("topic_title", row.get("query", ""))),
                                        source=self.source,
                                        description=f"Rising topic for '{kw}'",
                                        popularity_score=float(row.get("value", 5.0)),
                                    )
                                )
                except Exception as e:
                    logger.warning("google_trends_related_failed", error=str(e))

        except Exception as e:
            logger.warning("google_trends_collection_failed", error=str(e))

        logger.info("google_trends_collected", count=len(trends))
        return trends


class RedditCollector(TrendCollector):
    """Collect trending topics from Reddit subreddits."""

    source = TrendSource.REDDIT

    def collect(self, niche: NicheConfig) -> list[RawTrend]:
        logger.info("collecting_reddit_trends", niche=niche.name)
        trends: list[RawTrend] = []

        if not settings.reddit_client_id:
            logger.warning("reddit_not_configured")
            return trends

        try:
            import praw

            reddit = praw.Reddit(
                client_id=settings.reddit_client_id,
                client_secret=settings.reddit_client_secret,
                user_agent=settings.reddit_user_agent,
            )

            for sub_name in niche.subreddits[:3]:
                try:
                    subreddit = reddit.subreddit(sub_name)
                    for post in subreddit.hot(limit=10):
                        if post.stickied:
                            continue
                        trends.append(
                            RawTrend(
                                topic=post.title,
                                source=self.source,
                                url=f"https://reddit.com{post.permalink}",
                                description=post.selftext[:200] if post.selftext else "",
                                popularity_score=min(post.score / 1000, 10.0),
                            )
                        )
                except Exception as e:
                    logger.warning("reddit_subreddit_failed", subreddit=sub_name, error=str(e))

        except Exception as e:
            logger.warning("reddit_collection_failed", error=str(e))

        logger.info("reddit_trends_collected", count=len(trends))
        return trends


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
            resp = self._client.get(
                "https://newsapi.org/v2/top-headlines",
                params={
                    "category": niche.news_category,
                    "language": "en",
                    "pageSize": 10,
                    "apiKey": settings.news_api_key,
                },
            )
            resp.raise_for_status()
            data = resp.json()

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
            resp = self._client.get(
                "https://hacker-news.firebaseio.com/v0/topstories.json"
            )
            resp.raise_for_status()
            story_ids = resp.json()[:15]

            for story_id in story_ids:
                try:
                    detail = self._client.get(
                        f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
                    )
                    detail.raise_for_status()
                    story = detail.json()

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

    def collect(self, niche: NicheConfig) -> list[RawTrend]:
        logger.info("collecting_youtube_trends", niche=niche.name)
        trends: list[RawTrend] = []

        if not settings.youtube_api_key:
            logger.warning("youtube_api_not_configured")
            return trends

        try:
            resp = self._client.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={
                    "part": "snippet,statistics",
                    "chart": "mostPopular",
                    "regionCode": "US",
                    "videoCategoryId": niche.youtube_category_id,
                    "maxResults": 10,
                    "key": settings.youtube_api_key,
                },
            )
            resp.raise_for_status()
            data = resp.json()

            for item in data.get("items", []):
                snippet = item.get("snippet", {})
                stats = item.get("statistics", {})
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


class ViralityScorer:
    """Score trends for virality potential using AI (Gemini)."""

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def score(self, trends: list[RawTrend], niche: NicheConfig) -> list[ScoredTrend]:
        logger.info("scoring_virality", count=len(trends), niche=niche.name)

        if not trends:
            return []

        if not settings.gemini_api_key:
            logger.warning("gemini_not_configured_using_heuristic")
            return self._heuristic_score(trends, niche)

        try:
            import google.generativeai as genai

            genai.configure(api_key=settings.gemini_api_key)
            model = genai.GenerativeModel(settings.ai_model)

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

            response = model.generate_content(prompt)
            text = response.text.strip()

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
