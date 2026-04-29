"""
Run the full daily content pipeline (same behavior as `python main.py run`).

Usage:
  python run_pipeline.py
  python run_pipeline.py --dry-run
  python run_pipeline.py -n technology -n finance
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(_ROOT / ".env", override=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the AI Content Empire daily pipeline.")
    parser.add_argument(
        "-n",
        "--niches",
        action="append",
        default=None,
        metavar="NAME",
        help="Niche name(s) to run (repeatable). Default: all niches in config/niches.yaml.",
    )
    parser.add_argument(
        "-d",
        "--dry-run",
        action="store_true",
        help="Skip publishing and heavy media steps (same as main.py run --dry-run).",
    )
    args = parser.parse_args()

    from config.settings import settings
    from src.core.db import init_database
    from src.utils.logger import configure_logging, get_logger
    from src.orchestrator.pipeline import DailyRunner

    configure_logging(level=settings.log_level, environment=settings.env)
    init_database()
    log = get_logger("run_pipeline")

    runner = DailyRunner()
    report = None
    try:
        report = runner.run_all(niche_names=args.niches, dry_run=args.dry_run)
        log.info(
            "run_pipeline_complete",
            total=report.total_jobs,
            completed=report.completed,
            failed=report.failed,
            published=report.published,
        )
        print(
            f"Pipeline finished: jobs={report.total_jobs} completed={report.completed} "
            f"failed={report.failed} published={report.published}",
            file=sys.stderr,
        )
    finally:
        runner.close()

    if report is None:
        return 1
    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
