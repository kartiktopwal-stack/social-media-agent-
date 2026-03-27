"""
main.py
─────────────────────────────────────────────────────────────────────────────
CLI entry-point for the AI Content Empire.
"""

from __future__ import annotations

import sys
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from config.settings import settings
from src.core.db import init_database
from src.utils.logger import configure_logging, get_logger

app = typer.Typer(
    name="content-empire",
    help="🎬 AI Content Empire — Automated Social Media Publishing Engine",
    no_args_is_help=True,
)

console = Console()
logger = get_logger("main")


def _setup() -> None:
    """Initialize logging and database."""
    configure_logging(level=settings.log_level, environment=settings.env)
    init_database()


# ─── RUN ──────────────────────────────────────────────────────────────────────

@app.command()
def run(
    niches: Optional[list[str]] = typer.Option(None, "--niches", "-n", help="Niche names to run"),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-d",
        is_flag=True,
        help="Enable dry-run mode (skip publishing + media rendering)",
    ),
) -> None:
    """Run the complete daily pipeline for all (or selected) niches."""
    _setup()
    from src.orchestrator.pipeline import DailyRunner

    console.print("\n[bold green]Starting AI Content Empire Pipeline[/bold green]\n")

    try:
        dry_run_enabled = dry_run or ("--dry-run" in sys.argv) or ("-d" in sys.argv)
        runner = DailyRunner()
        report = runner.run_all(niche_names=niches, dry_run=bool(dry_run_enabled))

        table = Table(title="Daily Report", show_header=True, header_style="bold magenta")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="white")

        table.add_row("Date", report.date)
        table.add_row("Total Jobs", str(report.total_jobs))
        table.add_row("Completed", f"[green]{report.completed}[/green]")
        table.add_row("Failed", f"[red]{report.failed}[/red]" if report.failed else "[green]0[/green]")
        table.add_row("Published", str(report.published))

        if report.top_topic:
            table.add_row("Top Topic", report.top_topic[:60])
            table.add_row("Virality", f"{report.top_virality_score:.1f}/10")

        if report.niches_covered:
            table.add_row("Niches Active", ", ".join(report.niches_covered))

        console.print(table)

        if report.errors:
            console.print(f"\n[yellow]Errors ({len(report.errors)}):[/yellow]")
            for err in report.errors[:5]:
                console.print(f"  [red]- {err[:100]}[/red]")

        runner.close()

    except KeyboardInterrupt:
        console.print("\n[yellow]Pipeline interrupted by user.[/yellow]")
        sys.exit(130)
    except Exception as e:
        logger.error("pipeline_run_failed", error=str(e))
        console.print(f"\n[red]Pipeline failed: {e}[/red]")
        sys.exit(1)


# ─── TRENDS ───────────────────────────────────────────────────────────────────

@app.command()
def trends(
    niches: Optional[list[str]] = typer.Option(None, "--niches", "-n"),
) -> None:
    """Run only the trend collection step and print results."""
    _setup()

    from src.orchestrator.pipeline import load_niches
    from src.trend_engine.collector import TrendAggregator

    all_niches = load_niches()
    target = niches or list(all_niches.keys())
    aggregator = TrendAggregator()

    for name in target:
        cfg = all_niches.get(name)

        if not cfg:
            console.print(f"[red]Unknown niche: {name}[/red]")
            continue

        console.print(f"\n[bold cyan]Trends for: {name}[/bold cyan]")

        try:
            scored = aggregator.run(cfg)

            table = Table(show_header=True, header_style="bold blue")
            table.add_column("#", width=3)
            table.add_column("Score", width=6)
            table.add_column("Topic", width=60)
            table.add_column("Source", width=20)

            for i, t in enumerate(scored, 1):
                table.add_row(
                    str(i),
                    f"{t.virality_score:.1f}",
                    t.topic[:58],
                    ", ".join(t.sources[:2]),
                )

            console.print(table)

        except Exception as e:
            logger.error("trend_collection_failed", niche=name, error=str(e))
            console.print(f"[red]Failed to collect trends for {name}: {e}[/red]")

    aggregator.close()


# ─── SCRIPTS ──────────────────────────────────────────────────────────────────

@app.command()
def scripts(
    niches: Optional[list[str]] = typer.Option(None, "--niches", "-n"),
    topic: Optional[str] = typer.Option(None, "--topic", "-t"),
) -> None:
    """Run trend collection + script generation and print scripts."""
    _setup()

    from src.orchestrator.pipeline import load_niches
    from src.script_generator.generator import ScriptGenerator
    from src.trend_engine.collector import TrendAggregator
    from src.utils.models import Platform, ScoredTrend

    all_niches = load_niches()
    target = niches or list(all_niches.keys())[:1]

    aggregator = TrendAggregator()
    generator = ScriptGenerator()

    for name in target:
        cfg = all_niches.get(name)

        if not cfg:
            console.print(f"[red]Unknown niche: {name}[/red]")
            continue

        try:
            if topic:
                scored = [ScoredTrend(niche=name, topic=topic, virality_score=9.0)]
            else:
                scored = aggregator.run(cfg)[:1]

            for trend in scored:
                console.print(f"\n[bold yellow]Script for: {trend.topic}[/bold yellow]")

                script = generator.generate(trend, cfg, Platform.YOUTUBE)

                console.print(f"\n[bold red]HOOK:[/bold red] {script.sections.hook}")
                console.print("\n[bold blue]BODY:[/bold blue]")

                for line in script.sections.body:
                    console.print(f"  - {line}")

                console.print(f"\n[bold green]CTA:[/bold green] {script.sections.cta}")

                console.print(
                    f"\n[dim]Words: {script.word_count} | "
                    f"Est. duration: {script.estimated_duration_s:.1f}s[/dim]"
                )

        except Exception as e:
            logger.error("script_generation_failed", niche=name, error=str(e))
            console.print(f"[red]Failed for {name}: {e}[/red]")

    aggregator.close()


# ─── HEALTH CHECK ─────────────────────────────────────────────────────────────

@app.command()
def health() -> None:
    """Check all API connections and configuration."""
    _setup()

    console.print("\n[bold]System Health Check[/bold]\n")

    checks = {
        "Gemini API Key (AI + Scoring)": bool(settings.gemini_api_key),
        "Pexels API Key (Video)": bool(settings.pexels_api_key),
        "NewsAPI Key (Trends)": bool(settings.news_api_key),
        "YouTube API Key": bool(settings.youtube_api_key),
        "Reddit Credentials": bool(settings.reddit_client_id),
        "Twitter Credentials": bool(settings.twitter_api_key),
        "Object Storage": settings.object_storage_backend,
        "Telegram Configured": bool(settings.telegram_bot_token),
        "Environment": settings.env,
    }

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Check", style="cyan", width=35)
    table.add_column("Status", width=15)

    all_good = True
    critical = {"Gemini API Key (AI + Scoring)", "Pexels API Key (Video)", "NewsAPI Key (Trends)"}

    for check, value in checks.items():

        if isinstance(value, bool):
            if value:
                status = "[green]OK[/green]"
            elif check in critical:
                status = "[red]MISSING (critical)[/red]"
                all_good = False
            else:
                status = "[yellow]Not configured[/yellow]"
        else:
            status = f"[blue]{value}[/blue]"

        table.add_row(check, status)

    console.print(table)

    if all_good:
        console.print("\n[bold green]System ready to run![/bold green]")
    else:
        console.print("\n[bold red]Missing critical API keys. Check .env file.[/bold red]")
        sys.exit(1)


# ─── SERVER ───────────────────────────────────────────────────────────────────

@app.command()
def server(
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(8000, "--port"),
) -> None:
    """Start the FastAPI monitoring dashboard."""
    _setup()

    import uvicorn

    console.print(f"\n[bold green]Starting dashboard at http://{host}:{port}[/bold green]\n")

    uvicorn.run(
        "src.dashboard.app:app",
        host=host,
        port=port,
        reload=settings.env == "development",
    )


# ─── SCHEDULER ────────────────────────────────────────────────────────────────

@app.command()
def scheduler() -> None:
    """Start the automated daily scheduler."""
    _setup()

    from src.orchestrator.scheduler import start_scheduler

    console.print(f"\n[bold green]Starting scheduler (daily run at {settings.daily_run_hour}:00 UTC)[/bold green]\n")
    start_scheduler()


if __name__ == "__main__":
    app()
