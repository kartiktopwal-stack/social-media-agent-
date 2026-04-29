"""
scripts/test_trends_only.py
─────────────────────────────────────────────────────────────────────────────
Trends-only smoke test — runs each collector against the "technology" niche
and logs how many RawTrend objects each one returns.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on sys.path
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env", override=True)

from config.settings import settings
from src.utils.logger import configure_logging, get_logger
from src.utils.models import NicheConfig
from src.trend_engine.collector import (
    GoogleTrendsCollector,
    HackerNewsCollector,
    NewsAPICollector,
    RedditCollector,
    YouTubeTrendCollector,
)

configure_logging(level="INFO", environment=settings.env)
logger = get_logger("test_trends")


# ── Load the "technology" niche from niches.yaml ──────────────────────────

def load_technology_niche() -> NicheConfig:
    import yaml

    niches_path = _ROOT / "config" / "niches.yaml"
    with open(niches_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    raw = data["niches"]["technology"]
    return NicheConfig(name="technology", **raw)


def main() -> None:
    niche = load_technology_niche()
    print(f"\n{'='*60}")
    print(f"  TRENDS-ONLY TEST  —  niche: {niche.display_name}")
    print(f"{'='*60}")
    print(f"  keywords  : {niche.keywords}")
    print(f"  subreddits: {niche.subreddits}")
    print(f"  news_cat  : {niche.news_category}")
    print(f"  yt_cat_id : {niche.youtube_category_id}")
    print(f"{'='*60}\n")

    # ── Collectors ────────────────────────────────────────────────────────
    collectors = [
        ("google_trends", GoogleTrendsCollector()),
        ("reddit",        RedditCollector()),
        ("newsapi",       NewsAPICollector()),
        ("hackernews",    HackerNewsCollector()),
        ("youtube",       YouTubeTrendCollector()),
    ]

    results: dict[str, int] = {}

    for label, collector in collectors:
        print(f">>> Running: {label} ...")
        try:
            trends = collector.collect(niche)
            results[label] = len(trends)

            # Print first 3 topics as a quick sanity check
            for i, t in enumerate(trends[:3], 1):
                safe_topic = t.topic[:80].encode("ascii", errors="replace").decode("ascii")
                print(f"    {i}. [{t.source.value}] {safe_topic}  (pop={t.popularity_score:.1f})")

            if len(trends) > 3:
                print(f"    ... and {len(trends) - 3} more")

        except Exception as e:
            if label not in results:
                results[label] = -1
            print(f"    ERROR: {e}")
        finally:
            collector.close()

        print()

    # ── Summary ───────────────────────────────────────────────────────────
    print(f"{'='*60}")
    print(f"  SUMMARY: RawTrend counts per collector")
    print(f"{'='*60}")
    print(f"  {'Collector':<20} {'Count':>8}  {'Status':<10}")
    print(f"  {'-'*20} {'-'*8}  {'-'*10}")

    total = 0
    for label, count in results.items():
        if count < 0:
            status = "FAILED"
        elif count == 0:
            status = "EMPTY"
        else:
            status = "OK"
            total += count
        cnt_str = str(count) if count >= 0 else "—"
        print(f"  {label:<20} {cnt_str:>8}  {status:<10}")

    print(f"  {'-'*20} {'-'*8}  {'-'*10}")
    print(f"  {'TOTAL':<20} {total:>8}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
