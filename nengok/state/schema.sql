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
    updated_at        TEXT NOT NULL
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
