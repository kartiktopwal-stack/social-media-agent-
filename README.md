# 🎬 AI Content Empire

> **Fully automated AI-powered content pipeline.**
> Trends → Scripts → Voice → Video → Publish — every day, zero manual work.

---

## What This Does

This system runs multiple social media channels across different niches **automatically**:

1. **Collects trending topics** from Google Trends, Reddit, YouTube, NewsAPI, and HackerNews every morning
2. **AI-scores** each topic for virality using Claude or GPT-4o
3. **Generates scripts** optimized for short-form video (60-second hooks, body, CTA)
4. **Creates voice-over** using ElevenLabs (per-niche dedicated voices)
5. **Downloads stock footage** from Pexels API (vertical/portrait clips)
6. **Assembles final video** with FFmpeg: visuals + voice + subtitles + music
7. **Publishes to** YouTube Shorts, Instagram Reels, TikTok, X/Twitter

---

## Architecture

```
[5 AM Daily Cron]
      │
      ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 1: Trend Analysis Engine                          │
│  Google Trends + Reddit + YouTube + NewsAPI + HackerNews│
│  → AI Virality Scorer (Claude/GPT-4o)                   │
└──────────────────────────┬──────────────────────────────┘
                           │  list[ScoredTrend]
                           ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 2: Script Generation AI                           │
│  Claude/GPT-4o → HOOK + BODY + CTA (60s script)         │
└──────────────────────────┬──────────────────────────────┘
                           │  GeneratedScript
                           ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 3: Media Production Pipeline                      │
│  ElevenLabs Voice → Pexels Clips → Whisper Subs         │
│  → FFmpeg Assembly → Final 1080×1920 MP4                 │
└──────────────────────────┬──────────────────────────────┘
                           │  FinalVideo
                           ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 4: Publishing Automation                          │
│  YouTube Shorts + Instagram Reels + TikTok + X/Twitter  │
└─────────────────────────────────────────────────────────┘
```

---

## Quick Start

### Prerequisites
- Docker Desktop installed and running
- Git
- A text editor

### Step 1 — Clone and setup
```bash
git clone <your-repo-url>
cd ai-content-empire
bash scripts/setup.sh
```

### Step 2 — Add API keys
```bash
nano .env    # or open in any text editor
```

**Minimum keys to get started (free tier available for all):**
```
ANTHROPIC_API_KEY=...    # Required for script generation + virality scoring
ELEVENLABS_API_KEY=...   # Required for voice generation
PEXELS_API_KEY=...       # Required for stock footage (free: 200 req/hour)
NEWS_API_KEY=...         # For news trends (free: 100 req/day)
```

Get keys at:
- Anthropic: https://console.anthropic.com
- ElevenLabs: https://elevenlabs.io (free tier: 10,000 chars/month)
- Pexels: https://www.pexels.com/api/ (free)
- NewsAPI: https://newsapi.org (free: 100 req/day)

### Step 3 — Check health
```bash
bash scripts/run.sh health
```

### Step 4 — Test trend collection (free, no video production)
```bash
bash scripts/run.sh trends technology
```

### Step 5 — Generate scripts only
```bash
bash scripts/run.sh scripts technology
```

### Step 6 — Full dry run (produces videos, skips publishing)
```bash
bash scripts/run.sh dry-run technology
```
Check `data/output/final/` for your produced videos!

### Step 7 — Full production run (publishes to social media)
```bash
bash scripts/run.sh full
```

---

## Project Structure

```
ai-content-empire/
├── main.py                        CLI entry-point
├── run_pipeline.py                Run full daily pipeline (same as `main.py run`)
├── requirements.txt               All Python dependencies
├── pyproject.toml                 Pytest config
├── .env.template                  Copy to .env and fill in keys
│
├── config/
│   ├── settings.py                Pydantic settings (typed + validated)
│   └── niches.yaml                Niche definitions + channel accounts
│
├── src/
│   ├── trend_engine/
│   │   └── collector.py           Google/Reddit/YouTube/NewsAPI/HN collectors
│   ├── script_generator/
│   │   └── generator.py           Claude/GPT-4o script writer
│   ├── media_producer/
│   │   └── producer.py            ElevenLabs + Pexels + Whisper + FFmpeg
│   ├── publisher/
│   │   └── publisher.py           YouTube/Instagram/TikTok/Twitter APIs
│   ├── orchestrator/
│   │   ├── pipeline.py            Master pipeline + daily runner
│   │   └── scheduler.py           Optional APScheduler (main.py scheduler)
│   ├── dashboard/
│   │   └── app.py                 FastAPI monitoring dashboard
│   └── utils/
│       ├── models.py              Shared Pydantic data models
│       └── logger.py              Structured logging
│
├── docker/
│   ├── Dockerfile                 Isolated container build
│   └── docker-compose.yml         Optional dashboard container only
│
├── scripts/
│   ├── setup.sh                   First-time setup
│   ├── run.sh                     All run commands
│   └── init_db.sql                Database schema
│
├── tests/
│   └── test_pipeline.py           Unit + integration tests
│
└── data/
    ├── output/
    │   ├── audio/                 Generated voice files (.mp3)
    │   ├── clips/                 Downloaded stock footage
    │   ├── video/                 Intermediate video files
    │   └── final/                 ✅ FINAL VIDEOS (.mp4) — ready to post
    ├── music/                     Put royalty-free .mp3 tracks here
    └── logs/                      Daily reports (JSON)
```

---

## Adding a New Niche

1. Open `config/niches.yaml`
2. Add a new block following the existing pattern:
```yaml
niches:
  your_niche_name:
    display_name: "Your Niche"
    description: "What this channel is about"
    tone: "the tone for scripts"
    keywords: ["keyword1", "keyword2"]
    subreddits: ["subreddit1"]
    youtube_category_id: "28"
    news_category: technology
    elevenlabs_voice_id: "voice_id_from_elevenlabs"
    elevenlabs_voice_name: "VoiceName"
    script_style: "dramatic_reveal"
    posting_times:
      youtube: 14
    platforms:
      youtube:
        channel_id: "your_channel_id"
```
3. Run `bash scripts/run.sh trends your_niche_name` to test
4. The system auto-detects it on the next daily run

---

## Running Tests

```bash
# Unit tests only (no API keys needed)
bash scripts/run.sh test

# All tests including integration (needs ANTHROPIC_API_KEY)
bash scripts/run.sh test-integration
```

---

## Dashboard

After starting the Docker stack (`bash scripts/run.sh stack`), open **http://localhost:8000** for the FastAPI monitoring dashboard.

```bash
bash scripts/run.sh stack     # Build and start the dashboard container
bash scripts/run.sh stop      # Stop containers
bash scripts/run.sh logs app  # View app logs
```

For the full content pipeline (trends → publish), run on the host: `python run_pipeline.py` or `python main.py run`.

---

## Cost Estimate (5 niches, 3 videos/day/niche = 15 videos/day)

| Service     | Free Tier           | Paid Plan Needed At |
|-------------|---------------------|---------------------|
| Anthropic   | None (pay per use)  | ~$15/mo at this volume |
| ElevenLabs  | 10k chars/mo        | ~$22/mo (Creator) |
| Pexels      | 200 req/hr (free)   | Free forever        |
| NewsAPI     | 100 req/day (free)  | $449/mo (or use alternatives) |
| Pika/Runway | None                | ~$35/mo (if using AI video) |
| **VPS**     | —                   | ~$20/mo (Hetzner CX31) |
| **Total**   | **~$0** (testing)   | **~$90-150/mo** (production) |

---

## Platform API Setup (One-Time)

### YouTube
1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create project → Enable YouTube Data API v3
3. Create OAuth2 credentials → Download JSON
4. Run: `python scripts/youtube_auth.py` to get tokens

### Instagram / Meta
1. Go to [Meta for Developers](https://developers.facebook.com)
2. Create app → Add Instagram Graph API product
3. Connect Business/Creator Instagram account
4. Get long-lived access token (60-day expiry, auto-refresh)

### TikTok
1. Apply at [TikTok for Developers](https://developers.tiktok.com)
2. Create app → Request Content Posting API access
3. Note: approval takes 1-2 weeks

### X/Twitter
1. Apply for [Elevated access](https://developer.twitter.com)
2. Create app → Generate API keys and Access tokens
3. Enable Read + Write permissions

---

## License

Private project. Do not distribute API keys.
