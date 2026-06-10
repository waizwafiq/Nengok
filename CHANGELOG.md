# Changelog

Notable changes to Nengok, newest first. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project versions with [SemVer](https://semver.org/). The `github-release` job in [.github/workflows/publish.yml](.github/workflows/publish.yml) quotes the matching section of this file into the GitHub Release draft on every tag push, so keep section headers in the `## [x.y.z] - YYYY-MM-DD` shape.

## [0.1.0] - 2026-06-10

First public release.

### Added

- The full observe, diagnose, fix, verify loop over Arize Phoenix traces: rule-based anomaly filtering, Gemini-backed failure clustering with stable cluster identity across cycles, root-cause hypotheses, minimal prompt-diff proposals, generated regression suites (5 to 20 cases per cluster), and real Phoenix experiments gating every fix behind a pass-rate threshold.
- Human-in-the-loop by construction: no fix applies without an approval recorded in the audit log, and every approve, reject, dismiss, or escalate decision carries the reviewer, reason, timestamp, and source surface.
- CLI: `nengok init` (interactive wizard with connectivity probes), `run`, `watch` (circuit breaker plus graceful shutdown), `dashboard`, `review` (Textual TUI), `doctor`, `config show` / `config init --template`, `db migrate` / `status` / `check`, `export`, `reviewer`, and `improve`.
- State store on SQLAlchemy 2.0 Core: SQLite by default at `~/.nengok/state.db`, Postgres and MySQL via `DATABASE_URL`, Alembic migrations namespaced under the `nengok_` table prefix, TLS required for non-loopback hosts, and credential redaction in every log path.
- React dashboard with overview metrics (MTTD, MTTR, close rate, spend), cluster detail with prompt diff and per-case experiment tables, approval history, bearer-token auth, per-IP rate limiting, `/health`, and optional Prometheus `/metrics`.
- Multi-agent monitoring: one cycle observes every configured Phoenix project, cross-agent failure linking, reviewer feedback fed back into the clusterer, and a retro loop (`nengok improve`) that proposes clustering prompt amendments for human activation.
- ADK triage agent over the pinned Phoenix MCP server that decides per cycle whether the pipeline should wake.
- PII redaction before any span text leaves the process, with a pluggable scrubber escape hatch.
- Bundled Travel Planner and Q&A sample agents with injectable failure modes, golden datasets, and a one-command seed script.
- Resilience controls: Gemini retry with exponential backoff, per-call timeouts, a per-cycle token budget with incident artifacts, and structured JSON logging.
- Cloud Run deployment path with Vertex AI, Secret Manager, and Managed Prometheus integrations.

[0.1.0]: https://github.com/waizwafiq/Nengok/releases/tag/v0.1.0
