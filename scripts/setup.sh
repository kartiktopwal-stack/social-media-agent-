#!/usr/bin/env bash
set -euo pipefail

echo "=========================================="
echo "  AI Content Empire — First-Time Setup"
echo "=========================================="

# Check Python version
python3 --version || { echo "ERROR: Python 3.10+ required"; exit 1; }

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "→ Creating virtual environment..."
    python3 -m venv venv
fi

echo "→ Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "→ Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Create data directories
echo "→ Creating data directories..."
mkdir -p data/output/audio data/output/clips data/output/video data/output/final
mkdir -p data/music data/logs data/workspaces data/object_store

# Copy .env template if no .env exists
if [ ! -f ".env" ]; then
    echo "→ Creating .env from template..."
    cp .env.template .env
    echo "  ⚠  Edit .env and add your API keys!"
fi

# Check for ffmpeg
if command -v ffmpeg &>/dev/null; then
    echo "→ ffmpeg: $(ffmpeg -version 2>&1 | head -1)"
else
    echo "  ⚠  ffmpeg not found. Install it:"
    echo "     Ubuntu: sudo apt install ffmpeg"
    echo "     macOS:  brew install ffmpeg"
fi

# Initialize database
echo "→ Initializing database..."
python3 -c "from src.core.db import init_database; init_database()" 2>/dev/null || echo "  (will initialize on first run)"

echo ""
echo "=========================================="
echo "  Setup complete!"
echo ""
echo "  Next steps:"
echo "    1. Edit .env with your API keys"
echo "    2. bash scripts/run.sh health"
echo "    3. bash scripts/run.sh trends technology"
echo "=========================================="
