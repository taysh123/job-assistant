-- Job Assistant schema. Safe to run repeatedly (idempotent).

CREATE TABLE IF NOT EXISTS jobs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    dedup_key           TEXT NOT NULL UNIQUE,
    source              TEXT NOT NULL,
    external_id         TEXT NOT NULL DEFAULT '',
    title               TEXT NOT NULL,
    company             TEXT NOT NULL DEFAULT '',
    location            TEXT NOT NULL DEFAULT '',
    remote_flag         INTEGER NOT NULL DEFAULT 0,
    url                 TEXT NOT NULL,
    posted_at           TEXT,                       -- ISO-8601, source-provided
    summary             TEXT NOT NULL DEFAULT '',
    match_reasons       TEXT NOT NULL DEFAULT '[]', -- JSON array
    score               INTEGER NOT NULL DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'new', -- new|saved|ignored|opened|applied
    telegram_message_id INTEGER,
    first_seen_at       TEXT NOT NULL,              -- ISO-8601 UTC
    last_status_at      TEXT NOT NULL               -- ISO-8601 UTC
);

CREATE INDEX IF NOT EXISTS idx_jobs_status      ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_first_seen  ON jobs(first_seen_at);
CREATE INDEX IF NOT EXISTS idx_jobs_source      ON jobs(source);

-- One row per scheduled run; gates "once per day/week" and feeds stats.
CREATE TABLE IF NOT EXISTS runs (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    kind    TEXT NOT NULL,            -- collect|weekly
    ran_at  TEXT NOT NULL,           -- ISO-8601 UTC
    counts  TEXT NOT NULL DEFAULT '{}' -- JSON
);

CREATE INDEX IF NOT EXISTS idx_runs_kind_ran ON runs(kind, ran_at);

-- Small key/value store (e.g. Telegram getUpdates offset).
CREATE TABLE IF NOT EXISTS bot_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
