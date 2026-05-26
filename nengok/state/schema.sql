-- Nengok local state schema.
-- Applied idempotently by `StateStore.__init__`.

CREATE TABLE IF NOT EXISTS clusters (
    cluster_id        TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    description       TEXT,
    status            TEXT NOT NULL,
    hypothesis_json   TEXT,
    member_spans_json TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    first_seen        TEXT,
    diagnosed_at      TEXT
);

CREATE INDEX IF NOT EXISTS clusters_status_idx ON clusters (status);

CREATE TABLE IF NOT EXISTS seen_spans (
    span_id    TEXT PRIMARY KEY,
    cluster_id TEXT,
    first_seen TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approvals (
    approval_id TEXT PRIMARY KEY,
    cluster_id  TEXT NOT NULL,
    decision    TEXT NOT NULL,        -- approved | rejected | dismissed
    decided_by  TEXT,
    decided_at  TEXT NOT NULL,
    notes       TEXT,
    FOREIGN KEY (cluster_id) REFERENCES clusters (cluster_id)
);

CREATE INDEX IF NOT EXISTS approvals_cluster_idx ON approvals (cluster_id);

CREATE TABLE IF NOT EXISTS experiments (
    row_id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id              TEXT,
    cluster_id                 TEXT NOT NULL,
    experiment_name            TEXT NOT NULL,
    dataset_name               TEXT NOT NULL,
    baseline_pass_rate         REAL NOT NULL,
    fix_pass_rate              REAL NOT NULL,
    golden_baseline_pass_rate  REAL NOT NULL,
    golden_fix_pass_rate       REAL NOT NULL,
    per_case_json              TEXT NOT NULL,
    created_at                 TEXT NOT NULL,
    FOREIGN KEY (cluster_id) REFERENCES clusters (cluster_id)
);

CREATE INDEX IF NOT EXISTS experiments_cluster_idx ON experiments (cluster_id);
CREATE INDEX IF NOT EXISTS experiments_created_idx ON experiments (created_at);

CREATE TABLE IF NOT EXISTS cycles (
    cycle_id        TEXT PRIMARY KEY,
    started_at      TEXT NOT NULL,
    ended_at        TEXT NOT NULL,
    gemini_tokens   INTEGER NOT NULL DEFAULT 0,
    gemini_dollars  REAL NOT NULL DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS cycles_started_idx ON cycles (started_at);
