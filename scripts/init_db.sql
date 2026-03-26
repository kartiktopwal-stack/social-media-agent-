-- ═══════════════════════════════════════════════════════════════════════════
--  AI Content Empire — Database Schema
--  For Supabase/PostgreSQL production deployment
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS trends (
    id          SERIAL PRIMARY KEY,
    niche       TEXT NOT NULL,
    topic       TEXT NOT NULL,
    source      TEXT NOT NULL,
    virality    REAL DEFAULT 0,
    description TEXT DEFAULT '',
    collected_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS scripts (
    id          SERIAL PRIMARY KEY,
    trend_id    INTEGER REFERENCES trends(id),
    niche       TEXT NOT NULL,
    title       TEXT NOT NULL,
    hook        TEXT DEFAULT '',
    body        TEXT DEFAULT '',
    cta         TEXT DEFAULT '',
    full_text   TEXT DEFAULT '',
    word_count  INTEGER DEFAULT 0,
    platform    TEXT DEFAULT 'youtube',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS jobs (
    id           SERIAL PRIMARY KEY,
    job_id       TEXT UNIQUE NOT NULL,
    niche        TEXT NOT NULL,
    status       TEXT DEFAULT 'pending',
    trend_topic  TEXT DEFAULT '',
    script_id    INTEGER REFERENCES scripts(id),
    audio_path   TEXT DEFAULT '',
    video_path   TEXT DEFAULT '',
    final_path   TEXT DEFAULT '',
    error        TEXT DEFAULT '',
    started_at   TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS publish_log (
    id           SERIAL PRIMARY KEY,
    job_id       TEXT REFERENCES jobs(job_id),
    platform     TEXT NOT NULL,
    success      BOOLEAN DEFAULT FALSE,
    post_id      TEXT DEFAULT '',
    post_url     TEXT DEFAULT '',
    error        TEXT DEFAULT '',
    published_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_trends_niche ON trends(niche);
CREATE INDEX IF NOT EXISTS idx_trends_collected ON trends(collected_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_niche ON jobs(niche);
CREATE INDEX IF NOT EXISTS idx_jobs_started ON jobs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_publish_job ON publish_log(job_id);
