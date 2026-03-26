#!/usr/bin/env bash
set -euo pipefail

# Activate venv if it exists
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

COMMAND="${1:-help}"
shift 2>/dev/null || true

case "$COMMAND" in
    health)
        echo "🏥 Running health check..."
        python main.py health
        ;;

    trends)
        NICHE="${1:-}"
        if [ -n "$NICHE" ]; then
            echo "📊 Collecting trends for: $NICHE"
            python main.py trends --niches "$NICHE"
        else
            echo "📊 Collecting trends for all niches..."
            python main.py trends
        fi
        ;;

    scripts)
        NICHE="${1:-}"
        if [ -n "$NICHE" ]; then
            echo "✍️ Generating scripts for: $NICHE"
            python main.py scripts --niches "$NICHE"
        else
            echo "✍️ Generating scripts..."
            python main.py scripts
        fi
        ;;

    dry-run)
        NICHE="${1:-}"
        if [ -n "$NICHE" ]; then
            echo "🎬 Dry run for: $NICHE"
            python main.py run --niches "$NICHE" --dry-run
        else
            echo "🎬 Full dry run (all niches)..."
            python main.py run --dry-run
        fi
        ;;

    full)
        echo "🚀 FULL PRODUCTION RUN"
        echo "This will collect trends, generate content, and PUBLISH to social media."
        read -p "Are you sure? (y/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            python main.py run
        else
            echo "Cancelled."
        fi
        ;;

    server|dashboard)
        echo "🖥️ Starting dashboard server..."
        python main.py server
        ;;

    scheduler)
        echo "⏰ Starting scheduler..."
        python -c "from src.orchestrator.scheduler import start_scheduler; start_scheduler()"
        ;;

    stack)
        echo "🐳 Starting full Docker stack..."
        docker compose -f docker/docker-compose.yml up -d --build
        echo "Dashboard: http://localhost:8000"
        ;;

    stop)
        echo "🛑 Stopping Docker stack..."
        docker compose -f docker/docker-compose.yml down
        ;;

    logs)
        SERVICE="${1:-app}"
        docker compose -f docker/docker-compose.yml logs -f "$SERVICE"
        ;;

    test)
        echo "🧪 Running unit tests..."
        python -m pytest tests/ -v -m "not integration" --tb=short
        ;;

    test-integration)
        echo "🧪 Running all tests (including integration)..."
        python -m pytest tests/ -v --tb=short
        ;;

    help|*)
        echo "=========================================="
        echo "  AI Content Empire — Run Commands"
        echo "=========================================="
        echo ""
        echo "  bash scripts/run.sh <command> [args]"
        echo ""
        echo "  Commands:"
        echo "    health              Check API keys and config"
        echo "    trends [niche]      Collect trending topics"
        echo "    scripts [niche]     Generate video scripts"
        echo "    dry-run [niche]     Full run without publishing"
        echo "    full                Full production run (publishes!)"
        echo "    server              Start monitoring dashboard"
        echo "    scheduler           Start daily scheduler"
        echo "    stack               Start Docker stack"
        echo "    stop                Stop Docker stack"
        echo "    logs [service]      View Docker logs"
        echo "    test                Run unit tests"
        echo "    test-integration    Run all tests"
        echo "    help                Show this help"
        echo ""
        ;;
esac
