# Audit export

`nengok export` dumps the local state database as a portable bundle a
compliance reviewer can archive, diff, and ingest into another system.
The JSON shape documented here is a stable contract: new fields can be
appended at the end of their section, but field renames and removals
are forbidden once shipped. The same bundle is the seed for the v1.0 EU
AI Act audit bundle (proposal section 12.6).

## Running the export

```bash
# All-time bundle, JSON to stdout
nengok export > audit.json

# Calendar Q1, written to a file
nengok export --since 2026-01-01 --until 2026-03-31 --output audit-q1.json

# Spreadsheet-friendly bundle (clusters + approvals only)
nengok export --since 2026-01-01 --format csv --output audit.csv
```

Both `--since` and `--until` are optional. Either bound omitted means
"no lower bound" or "no upper bound" respectively. Dates are parsed as
UTC midnight, and `--until` is inclusive of the named day: the example
above covers everything up to and including 31 March 2026.

If `--output` is omitted the rendered bundle goes to stdout so it
composes with the usual shell redirect (`> audit.json`). With
`--output` the parent directory is created if needed and a one-line
summary is logged to stderr so the JSON file stays clean.

## JSON schema

```jsonc
{
  "export_version": 1,
  "nengok_version": "0.1.0",
  "generated_at": "2026-05-27T08:30:00+00:00",
  "filter": {
    "since": "2026-01-01",   // null when --since not passed
    "until": "2026-03-31"    // null when --until not passed
  },
  "counts": {
    "clusters": 3,
    "approvals": 5,
    "experiments": 4,
    "cycles": 12,
    "artifacts": 3
  },
  "clusters": [
    {
      "cluster_id": "c-abc123",
      "name": "weather tool unit mismatch",
      "description": "...",
      "status": "approved",
      "hypothesis": {
        "summary": "...",
        "expected_behavior": "...",
        "actual_behavior": "...",
        "likely_cause": "...",
        "implicated_tools": ["weather"]
      },
      "member_span_ids": ["span-1", "span-2"],
      "created_at": "2026-02-12T10:11:12+00:00",
      "updated_at": "2026-02-12T11:00:00+00:00",
      "first_seen": "2026-02-12T10:11:12+00:00",
      "diagnosed_at": "2026-02-12T10:14:00+00:00"
    }
  ],
  "approvals": [
    {
      "approval_id": "9c2c...",
      "cluster_id": "c-abc123",
      "decision": "approved",        // approved | rejected | dismissed | escalated
      "reviewer": "alice@example.com",
      "reason": "matches the existing prompt phrasing",
      "created_at": "2026-02-12T11:00:00+00:00"
    }
  ],
  "experiments": [
    {
      "experiment_id": "exp-7f...",
      "cluster_id": "c-abc123",
      "experiment_name": "fix-vs-baseline c-abc123",
      "dataset_name": "regression c-abc123",
      "baseline_pass_rate": 0.42,
      "fix_pass_rate": 0.95,
      "golden_baseline_pass_rate": 0.88,
      "golden_fix_pass_rate": 0.91,
      "per_case": [{"case_id": "...", "baseline": false, "fix": true}],
      "created_at": "2026-02-12T10:30:00+00:00"
    }
  ],
  "cycles": [
    {
      "cycle_id": "2026-02-12T10:00:00Z",
      "started_at": "2026-02-12T10:00:00+00:00",
      "ended_at": "2026-02-12T10:15:00+00:00",
      "gemini_tokens": 124500,
      "gemini_dollars": 0.74
    }
  ],
  "artifacts": [
    {
      "cluster_id": "c-abc123",
      "directory": "artifacts/c-abc123",   // null when no bundle exists on disk
      "files": [
        {"name": "prompt.md",      "size_bytes": 1024, "sha256": "..."},
        {"name": "rca.md",         "size_bytes": 2048, "sha256": "..."},
        {"name": "regression.json","size_bytes": 4096, "sha256": "..."}
      ]
    }
  ]
}
```

Every timestamp is an ISO 8601 string with an explicit UTC offset. The
`artifacts[].directory` value is a POSIX-style relative path so the
bundle is portable across operating systems. The `sha256` field for
each artifact file is computed at export time and lets a downstream
auditor verify that nothing has been edited since the bundle was
produced.

## Stability contract

- `export_version` starts at `1`. It is bumped on a breaking change to
  the JSON shape, never for backwards-compatible additions.
- Field renames and removals are forbidden once shipped. A field that
  outlives its usefulness stays in the payload as `null` for two minor
  releases before deletion is even considered, and any such deletion
  bumps `export_version`.
- New fields land at the end of their section so a reader that pins
  on positional CSV-style ordering still works.
- The list sections (`clusters`, `approvals`, `experiments`, `cycles`,
  `artifacts`) are sorted by their primary timestamp ascending, with
  ties broken by the primary key. That ordering is stable across runs.

## CSV format

`--format csv` writes two header-prefixed sections to one file:

```text
# clusters
cluster_id,name,description,status,created_at,updated_at,first_seen,diagnosed_at,member_span_count
...

# approvals
approval_id,cluster_id,decision,reviewer,reason,created_at
...
```

The `# clusters` and `# approvals` marker lines let a spreadsheet user
split the file in two and import each section as its own table. Free
text fields (`description`, `reason`) are CSV-escaped per RFC 4180. The
full hypothesis, member span list, and experiment per-case detail are
deliberately omitted from CSV. Use JSON for an audit that needs those.
