# Contributing to Nengok

Thanks for your interest in Nengok. The SDK is the product (the dashboard is a thin local UI on top of it), so most contributions should land in `nengok/`.

This is a monorepo: the SDK, the dashboard frontend, the demo agent, and the Phoenix integration harness all live in one history. Cross-cutting changes ship as one PR.

## Getting Set Up

The short version: clone, install in a venv, copy `.env.example` to `.env`, start Phoenix, generate traces with the sample agent, run `nengok`. Every step below has the Windows command first, then macOS/Linux. Run everything from the repo root unless a step says otherwise.

### Prerequisites

| Tool | Why | Where |
|---|---|---|
| Python 3.11+ | The SDK and demo agent | [python.org](https://www.python.org/downloads/) (Windows), Homebrew (macOS), distro package manager (Linux) |
| Node 22+ | Only if you touch `frontend/` | [nodejs.org](https://nodejs.org/) or `nvm` |
| Google AI Studio key | Gemini reasoning + judge | <https://aistudio.google.com/> |
| A Phoenix instance | Trace storage | Phoenix Cloud, self-hosted, or `phoenix serve` locally (covered in step 4) |

If you plan to use the `uv` install path, you do not need Python 3.11+ on the system; `uv` will download a managed CPython for you.

### 1. Clone the repo

```bash
git clone https://github.com/waizwafiq/Nengok.git .
```

`pyproject.toml` lives at the repo root. The `nengok/` subdirectory is the Python package and does not contain a manifest, so `cd nengok` before installing prints `does not appear to be a Python project`.

### 2. Install the SDK in editable mode

Pick `uv` (faster, bundles Python) or stock `pip` (already on most systems).

#### Option A: `uv` (recommended)

[`uv`](https://docs.astral.sh/uv/) is a drop-in replacement for `pip` + `venv` that ships managed Python builds and a shared wheel cache. Cold install: under 10 seconds.

**Windows (PowerShell or cmd):**

```bat
pip install --user uv
python -m uv python install 3.12
python -m uv venv --seed --python 3.12
.venv\Scripts\activate
python -m uv pip install -e ".[dev,phoenix,gemini]"
```

**macOS / Linux:**

```bash
pip install --user uv
python -m uv python install 3.12
python -m uv venv --seed --python 3.12
source .venv/bin/activate
python -m uv pip install -e ".[dev,phoenix,gemini]"
```

If `uv` is not on your PATH after `pip install --user uv`, keep invoking it as `python -m uv ...` or run `python -m uv python update-shell` once.

**Why `--seed`?** A bare `uv venv` does not install `pip` inside the venv. After activation, running plain `pip install <pkg>` then falls back to your *system* Python's pip and installs the package outside the venv, where Nengok cannot see it. `--seed` puts a real `pip` inside the venv so both `pip install` and `python -m uv pip install` write to the right place.

#### Option B: stock `pip`

Needs Python 3.11+ already installed and on your PATH. Cold install: 2 to 5 minutes on Windows because `uvicorn[standard]` pulls in a few Rust-built dependencies.

**Windows (PowerShell or cmd):**

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev,phoenix,gemini]"
```

**macOS / Linux:**

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,phoenix,gemini]"
```

You end up with Nengok in editable mode plus the dev extras (`ruff`, `pytest`, `mypy`), the Phoenix client, the Gemini SDK, and the OpenInference instrumentor that wraps it. Skip the `phoenix` extra only if you are working on internal modules that never touch `nengok.phoenix.client`; `nengok run` will not work without it. Skip the `gemini` extra only if you never run the sample agent; without it `_maybe_register_phoenix_tracing` configures a Phoenix project but the genai call emits no spans, so the `travel-planner-agent` project never gets created and `nengok run` 404s in step 6.

The editable install also runs `npm install && vite build` in `frontend/` via a hatchling build hook so the dashboard works out of the box. This needs Node 22+ on your PATH and adds roughly 30 seconds on a cold install. If you don't have Node or only plan to work on Python, set `NENGOK_SKIP_FRONTEND_BUILD=1` before `pip install` and the hook is a no-op. In that case, `nengok dashboard` still serves the API but `/` returns a JSON hint instead of the UI until you build the frontend manually.

### 3. Create your `.env`

**Windows (cmd):**

```bat
copy .env.example .env
```

**Windows (PowerShell):**

```powershell
Copy-Item .env.example .env
```

**macOS / Linux:**

```bash
cp .env.example .env
```

Open `.env` and fill in `GOOGLE_API_KEY` (and `PHOENIX_API_KEY` if your Phoenix needs auth). The defaults for `PHOENIX_BASE_URL=http://localhost:6006` and `NENGOK_PROJECT=travel-planner-agent` match every other step in this guide, so leave them alone unless your setup differs.

Nengok and the sample agent both auto-load `.env` from the current directory at startup (via `python-dotenv`), so you do not need to `export` anything in your shell. Run every command from the repo root and the env vars come along for free.

#### Pointing state at Postgres or MySQL

By default Nengok keeps cluster and approval state in a SQLite file at `~/.nengok/state.db`. To put state in a database you already run, set `DATABASE_URL` (for example `postgresql+psycopg://user:pass@host/db` or `mysql+pymysql://user:pass@host/db`) and re-run `nengok init`. The TOML key `database_url` accepts the same value if you prefer to keep it off the shell environment, and the env var wins when both are present. Anything outside the four supported dialects (`sqlite`, `postgresql`, `postgresql+psycopg`, `mysql`, `mysql+pymysql`) is rejected at config-load with a `ConfigError` so a typo surfaces before the orchestrator starts.

The engine is built once per process via `ConnectionFactory` in [nengok/state/connection.py](../nengok/state/connection.py) with `pool_size=5` and `max_overflow=5`, so Nengok holds at most ten connections at peak against a database it shares with your application.

#### Swapping the LLMs

The four Gemini models in the loop are all overridable via environment variables, so you can run the SDK against a different snapshot (or a non-public preview) without editing source or `~/.nengok/config.toml`:

| Env var | Default | What it drives |
|---|---|---|
| `NENGOK_DIAGNOSER_MODEL` | `gemini-3.1-pro-preview` | Clusterer + Hypothesizer + Prompt Proposer + Test Generator inside `nengok/core/` |
| `NENGOK_JUDGE_MODEL` | `gemini-3-flash-preview` | LLM-as-Judge evaluators wired through `nengok/core/evaluators/llm_judges.py` |
| `SAMPLE_AGENT_MODEL` | `gemini-2.5-flash` | The Travel Planner demo agent in `sample_agent/agent.py` |
| `QA_AGENT_MODEL` | `gemini-2.5-flash` | The retrieval-augmented Q&A agent in `sample_agent/qa_agent/agent.py` |

The two `NENGOK_*` vars feed `NengokConfig.diagnoser_model` and `NengokConfig.judge_model` through `_read_env()` in `nengok/config.py`, so they win over the on-disk TOML and lose to constructor overrides. The two sample-agent vars are read directly inside each agent's `build_*` / `answer_*` function. The defaults assume Gemini; swapping in a non-Gemini model requires more than an env-var bump because the agents call `google-genai` directly.

If you set one of these to a string Google does not recognise, every Gemini call routes through `nengok/utils/gemini.py::call_gemini` and the SDK raises `InvalidGeminiModelError` (or `GeminiAuthError` / `GeminiQuotaError` for 401/403/429) with a message that names the env var you configured. The error replaces the raw `google.genai.errors.ClientError` stack trace, so a typo surfaces as `Clusterer: model 'gemini-1.5-pro' is not a valid Gemini model. Override via the NENGOK_DIAGNOSER_MODEL env var.` instead of a 404 deep inside the call site.

#### When Gemini says 429

The free tier of `gemini-2.5-flash` is capped at 20 requests per day per project, which a few back-to-back `python -m sample_agent.seed --count 15` invocations will burn through. When the API answers 429, Nengok behaves differently depending on the entry point:

- **`python -m sample_agent.seed`** parses the API-suggested retry delay out of the `RetryInfo` block, sleeps that long plus one second of buffer, and retries the same query once. If the retry also 429s, the run is marked failed and the loop continues to the next query. The summary line at the end reports the surviving count.
- **`nengok run`** retries 429s and 5xx errors inside `call_gemini` with exponential backoff up to `gemini_max_retries` attempts (default 3), each attempt capped at `gemini_timeout_seconds` (default 45). When the retry budget exhausts, the CLI prints `Error (gemini-quota): ...` with the parsed retry delay and quota id, then exits 1.
- **`nengok watch`** applies the same per-call retries. A cycle that still fails afterwards prints `Cycle skipped in '<stage>' (gemini-quota): ...` to stderr and the loop sleeps until the next interval. Three consecutive failures in the same stage trip the circuit breaker, which pauses the loop for `circuit_breaker_backoff_seconds` (default 900s) and drops a `circuit-breaker.md` incident under `artifacts/incidents/<iso>/` so the operator can see the recent tracebacks without grepping logs.

To raise the cap, enable billing at <https://ai.dev/rate-limit> and the free-tier quotaId (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`) stops applying. To keep using free tier but make Nengok behave, point `NENGOK_DIAGNOSER_MODEL` and `SAMPLE_AGENT_MODEL` at different models so the daily caps don't share a bucket.

### 4. Start a local Phoenix (optional, for end-to-end work)

If you already have Phoenix Cloud or a remote Phoenix, point `PHOENIX_BASE_URL` and `PHOENIX_API_KEY` at it in `.env` and skip this step.

**All platforms** (run in a separate terminal so it stays up):

```bash
pip install arize-phoenix
phoenix serve
```

Phoenix UI: <http://localhost:6006>.

Nengok also talks to the `@arizeai/phoenix-mcp` npm package as a subprocess for read-side MCP operations. Pin to `@arizeai/phoenix-mcp@4.0.13`. There is no Python wheel; install with `npm i -g @arizeai/phoenix-mcp@4.0.13` if you plan to exercise the MCP read path. Bumping the pin is a deliberate change that should land in its own PR.

### 5. Generate traces with the sample agent

In a new terminal with the venv activated, run the seed helper to fire several Travel Planner runs with every failure mode injected:

**Windows:**

```bat
.venv\Scripts\activate
python -m sample_agent.seed --count 5
```

**macOS / Linux:**

```bash
source .venv/bin/activate
python -m sample_agent.seed --count 5
```

`sample_agent.seed` rotates through a small set of queries (so the clusters look like real traffic rather than identical replays), turns on all three demo failure modes (flights schema drift, weather unit mismatch, hotels timeout), and prints the resulting Phoenix project URL when it finishes. The clusterer needs roughly three anomalous traces before it can name a pattern, so `--count 5` is the floor; bump it higher if you want denser clusters. Pass `--inject flights|weather|hotels|none` to scope the failure modes, or `--query "..."` to pin every run to one prompt.

If you want a single one-shot run with no batching, the underlying agent still works directly:

```bash
python -m sample_agent.agent --inject all
```

`build_itinerary` now invokes Gemini via `google-genai`, so `phoenix.otel.register(auto_instrument=True)` has a real LLM call to wrap and the `openinference-instrumentation-google-genai` package emits spans on every run. Each invocation creates or updates the `travel-planner-agent` project in Phoenix, and `nengok run` against that project should pull anomalous spans without 404ing.

If the agent prints `WARNING: PHOENIX_BASE_URL is not set`, your `.env` is missing or you are running from the wrong directory.

### 6. Run a Nengok cycle

```bash
nengok init
nengok run
```

`nengok init` runs an interactive wizard. It auto-detects a local `phoenix serve` on port 6006 and offers it as the default, asks for your Gemini key (validated with a one-token ping so a wrong key is caught up front), and offers `travel-planner-agent` as the default project so the sample agent works without further flags. The wizard then runs three connectivity probes (Phoenix `GET /v1/projects`, a Gemini ping, and a file-write probe under `~/.nengok/`) and only writes `~/.nengok/config.toml` if every probe passes.

Every prompt has a flag equivalent for non-interactive use: `--phoenix-url`, `--phoenix-api-key`, `--google-api-key`, `--project`, `--agent-runner`. For CI or scripted setup, pass `--non-interactive` so the wizard never prompts (missing required values exit 2). Pass `--force` to write the config even if a probe fails, which is useful when Phoenix is reachable only from a different network.

If you would rather start from a documented template and edit by hand instead of running the wizard, use `nengok config init --template <name>`. The three shipped templates are `local` (local `phoenix serve` plus the bundled sample agent), `cloud` (Phoenix Cloud plus the bundled sample agent), and `qa-agent` (local Phoenix plus the retrieval-augmented Q&A sample agent). The same files live at [examples/config-local.toml](../examples/config-local.toml), [examples/config-cloud.toml](../examples/config-cloud.toml), and [examples/config-qa-agent.toml](../examples/config-qa-agent.toml) for browsing on GitHub, and the wizard seeds from the same files so the output of either path stays consistent.

Before the Observer fires, `nengok run` performs an MCP preflight against the configured Phoenix project. If `npx` is on PATH, the check spawns `@arizeai/phoenix-mcp@4.0.13`, calls `list_projects`, and prints a `Heads up: Phoenix project '...' was not found via MCP` line on stderr when the project is missing. The cycle still runs (the warning is best-effort), but the message tells you up front why the Observer is about to return zero spans. Pass `--skip-preflight` to suppress the check; set `NENGOK_MCP_ENABLED=0` to disable it for every run. If `npx` is missing, the preflight downgrades to a debug log and is a no-op.

For projects other than the bundled `travel-planner-agent`, the canonical path is to define a class that satisfies the `AgentRunner` Protocol from `nengok.runners.protocol` and point the config at it:

```python
# my_pkg/runner.py
from typing import Any


class MyAgent:
    @property
    def name(self) -> str:
        return "my-agent"

    def run(self, agent_input: dict[str, Any], prompt: str) -> dict[str, Any]:
        from my_pkg.agent import answer

        return answer(agent_input["query"], system_prompt=prompt)
```

```toml
# ~/.nengok/config.toml
agent_runner = "my_pkg.runner:MyAgent"
```

`nengok run` calls the runner once per dataset row with the candidate prompt injected, so a fix can be A/B'd against the baseline. If the dotted path is wrong or the class is missing `run` / `name`, the orchestrator raises `AgentRunnerLoadError` before the first Phoenix call. Imperative registration via `nengok.runners.register_runner("my-project", callable)` still works for bootstrap modules that prefer it. The longer walk-through lives in [docs/extending.md](../docs/extending.md).

The Fixer's baseline-prompt lookup is also pluggable. The default loader walks the bundled sample-agent file, then Phoenix prompt management, then `config.baseline_prompt_path`. Teams that keep their prompt elsewhere set `baseline_prompt_loader = "my_pkg.loaders:build"` in TOML and ship a factory that returns any object implementing `load(project_name: str) -> str | None`. The three reusable building blocks (`FileLoader`, `PhoenixPromptLoader`, `CompositeLoader`) live in [nengok/core/fixer/loaders.py](../nengok/core/fixer/loaders.py).

After a successful cycle Phoenix will hold two projects: your monitored project plus `nengok-meta-agent`, which stores the four-span trace per cycle (`nengok.cycle` -> `observer` / `diagnoser` / `fixer` / `verifier`) the orchestrator emits via `nengok.utils.tracing`. The meta-tracer needs `arize-phoenix-otel` (already in the `phoenix` extra). When the extra is missing, the spans silently drop and the loop runs as before.

If a later change breaks the install, run `nengok doctor` for a read-only sweep. Each probe lives under [nengok/diagnostics/](../nengok/diagnostics/) and reports one line of the same `[ok|warn|fail] name: detail` shape, with a copy-paste fix hint printed below each non-OK probe. The default set checks the config file, Phoenix reachability and project visibility, a Gemini one-token ping, the optional baseline prompt path, and the agent runner. Exit codes are 0 on all pass and 1 on any fail; pass `--strict` to also fail on warnings (useful when an empty Phoenix project would otherwise hide a setup mistake), or `--json` for a machine-readable payload that drops into a CI gate.

#### State migrations

Schema for the state store lives in [nengok/state/alembic/versions/](../nengok/state/alembic/versions/) as Alembic revisions. Every table starts with the `nengok_` prefix (`nengok_clusters`, `nengok_approvals`, `nengok_experiments`, `nengok_cycles`, `nengok_seen_spans`), and Alembic's own bookkeeping is namespaced too (`nengok_alembic_version`) so Nengok does not collide with the operator's existing schema or with their own `alembic_version` table when `DATABASE_URL` points at a database it shares with their application. Revisions are written as `op.create_table(...)` / `op.alter_column(...)` calls rather than raw SQL, so the same revision applies cleanly on SQLite, Postgres, and MySQL. The store calls `alembic upgrade head` on first connect; the legacy `schema_versions` table from earlier installs is detected, stamped at the matching Alembic revision, and dropped automatically, and a previous-install `alembic_version` table whose rows reference packaged Nengok revision ids is reconciled into `nengok_alembic_version` and dropped.

For full Postgres isolation, set `database_schema = "nengok"` in `~/.nengok/config.toml` (or export `NENGOK_DATABASE_SCHEMA=nengok`). Every Nengok table, every index, and the bookkeeping row then land in the named schema rather than `public`. SQLite ignores the setting. The grant trade-off is documented in [docs/database-grants.md](../docs/database-grants.md).

Three CLI helpers wrap the migrator. `nengok db migrate` runs `alembic upgrade head` against the configured database and prints either the new revision or `up to date`. `nengok db status` lists every packaged revision and marks which one the live database is stamped at. `nengok db check` exits 1 when the live revision does not match the packaged head, which makes a good gate for CI on the state package. To add a column or table, generate a new revision file under `alembic/versions/` and ship it in the same PR as the code that reads the new field; do not rewrite an earlier revision.

#### Approval audit log

Every approve, reject, dismiss, or escalate decision is written to the `approvals` table with the reviewer, free-text reason, and a UTC timestamp. The dashboard cluster detail page renders the full history under the approval card; the API exposes `GET /api/v1/clusters/{id}/approvals` for one cluster (newest first) and `GET /api/v1/approvals?limit=50&before=<approval_id>` for a keyset-paginated cross-cluster feed. `POST /api/v1/clusters/{id}/approvals` records a new decision and is what the dashboard talks to; the legacy `POST /api/v1/approvals` body shape (`cluster_id`, `decided_by`, `notes`) still works and routes through the same code path.

Reviewer identity is resolved in this order: the value supplied in the request body, then a single line in `~/.nengok/reviewer.txt`, then the `NENGOK_REVIEWER` environment variable, then the literal `anonymous`. The file beats the env var so a per-user identity is not silently overridden by a deployment-wide export. Set the file once with `nengok reviewer set "Your Name" --email you@example.com`, which writes the value in git-style `Name <email>` format and prints the path it wrote to. `nengok reviewer show` prints the currently resolved identity and which of the four sources supplied it. `GET /api/v1/reviewer` exposes the same answer to the dashboard, which uses it to surface a warning when the operator is about to record an action as `anonymous`. Leaving the reason blank is allowed; the textarea is there so reviewers can drop in a one-liner ("matches the existing prompt phrasing", "ships after Tuesday's release"), and the gate does not enforce it.

To inspect the resolved config without leaking keys, run `nengok config show`. Every field whose name matches `api_key`, `token`, `secret`, `password`, or `authorization` renders as `prefix****suffix` (for example `google_api_key = AIza****uvwx`), so the output is safe to drop in a paste buffer or a support ticket. Every Nengok process also writes one INFO line on startup that names the version, the config path actually read, the redactor state, and the Phoenix base URL (`nengok v0.1.0 starting (config: ~/.nengok/config.toml, redaction: enabled, phoenix: https://...)`). Operators can grep for `redaction: disabled` in a log shipper to catch a misconfigured deployment before it ships span text to Gemini in the clear.

#### State export

`nengok export --since YYYY-MM-DD --until YYYY-MM-DD > audit.json` writes the clusters, approvals, experiments, cycles, and per-cluster artifact pointers inside the date window as a single JSON bundle. Both bounds are optional and parsed as UTC midnight; `--until` is inclusive of the named day. Output goes to stdout by default so the shell redirect at the end of the command works as written; pass `--output PATH` to write to a file and get a one-line summary on stderr instead. Pass `--format csv` for a two-section CSV (`# clusters` then `# approvals`) that a reviewer can split and import into a spreadsheet. The JSON shape is documented in [docs/audit-export.md](../docs/audit-export.md) and is the seed for the v1.0 EU AI Act audit bundle, so field renames are forbidden once shipped (additions land at the end of their section). Every artifact entry includes a sha256 of each on-disk file so a downstream auditor can verify nothing has been edited since the bundle was produced.

#### Cycle history

Every `nengok run` writes one row to the `cycles` table at cycle end through `StateStore.record_cycle`, even when an unhandled exception escapes the loop. The row carries `status` (`ok`, `over_budget`, `circuit_broken`, or `failed`), `clusters_processed` versus `clusters_discovered`, the Gemini spend, and an `error_message` set from the exception when status is `failed`. The orchestrator wraps `run_once` in a try-block so a Phoenix outage or a Gemini quota error still leaves a record behind. The overview dashboard surfaces the last ten of those rows as a per-cycle spend sparkline and a stacked outcome histogram, so an operator can see "five cycles in a row went over budget" without grepping logs. The same fields land at the end of each `cycles[]` entry in `nengok export` so the audit bundle and the dashboard agree.

### 7. Launch the dashboard (optional)

```bash
nengok dashboard
```

This boots the FastAPI server on <http://localhost:8765> and opens your browser to it. The dashboard bundle was built and copied into `nengok/server/static/` during step 2, so the install ships with the UI and `nengok dashboard` serves it directly without a separate Node process.

Pass `--no-browser` to skip the auto-open.

If `/` returns a JSON hint instead of the UI, the install either skipped the frontend build (look for `NENGOK_SKIP_FRONTEND_BUILD=1` in your env) or `npm` wasn't on PATH. Run `cd frontend && npm install && npm run build`, then restart `nengok dashboard`.

#### Auth and network exposure

The dashboard binds to `127.0.0.1` by default and runs without auth. Pass `--listen 0.0.0.0` to expose it on the LAN and you will get a stderr warning that anyone on the network can read RCA documents. To require a token, set `dashboard_auth_token` in `~/.nengok/config.toml` (or `NENGOK_DASHBOARD_AUTH_TOKEN`); the FastAPI app then rejects `/api/v1/*` requests that lack `Authorization: Bearer <token>`, and the frontend pops a login screen on the first 401 so a reviewer can paste the token from `config.toml`. For Cloud Run set `NENGOK_PRODUCTION=true`; the dashboard refuses to start unless both the token is set and the bind address is not localhost. Override the CORS allowlist with `dashboard_cors_origins` in TOML, or `NENGOK_DASHBOARD_CORS_ORIGINS=https://nengok.example.com,https://staff.example.com`.

The dashboard server also rate-limits every `/api/v1/*` route at 60 requests per minute per source IP. Loopback addresses (`127.0.0.1`, `::1`) are exempt so calls from the dashboard owner's own machine run unconstrained. When a remote client exceeds the limit, the response is `429` with a JSON body (`{"error": "rate_limit_exceeded", ...}`) and a `Retry-After: 60` header, so curl, browsers, and Cloud Run back off for a minute before retrying.

For infrastructure probes the dashboard exposes `GET /health` outside the `/api/v1` prefix. The endpoint takes no auth, sits outside the rate limiter, and returns JSON of the form `{"status": "ok", "version": "0.1.0", "phoenix_reachable": bool, "gemini_reachable": bool, "db_writable": bool}`. Phoenix reachability is a short HTTP GET against `/v1/projects`, Gemini reachability is a 1-token ping against `gemini-2.5-flash`, and `db_writable` writes a sentinel file next to `state_db_path` and opens a SQLite connection. Both upstream checks are cached for 30 seconds so a Cloud Run or Kubernetes liveness probe firing every few seconds hits the cache instead of the upstream API.

#### Frontend development with HMR (recommended)

Use this loop when you're editing anything under `frontend/`: run the Vite dev server in one terminal and the FastAPI server in another. Vite hot-reloads on save, proxies `/api` calls to the FastAPI side, and leaves the pre-built bundle in `nengok/server/static/` untouched.

Terminal A, FastAPI server:

```bash
nengok dashboard --no-browser
```

Terminal B, Vite dev server.

**Windows:**

```bat
cd frontend
npm install
npm run dev
```

**macOS / Linux:**

```bash
cd frontend
npm install
npm run dev
```

Then open <http://localhost:5173>. Edits to any `.tsx` or `.ts` file show up on save.

#### Seeing frontend changes through `nengok dashboard`

`nengok dashboard` serves the bundle from `nengok/server/static/`, which is populated once by the hatch build hook in step 2 and does not refresh when you edit source. If you want to verify a change through the `8765` port instead of the Vite dev server, rebuild and reinstall:

```bash
cd frontend
npm run build
cd ..
pip install -e . --no-deps
```

The `pip install -e . --no-deps` re-fires the hatch hook so the new `dist/` copies into `nengok/server/static/`. Restart `nengok dashboard` afterwards. For day-to-day iteration the HMR loop above is faster; reach for the rebuild only when you need to sanity-check the production bundle.

## Branch Naming

| Prefix      | Use for                                  | Example                          |
| ----------- | ---------------------------------------- | -------------------------------- |
| `feat/`     | New features                             | `feat/hdbscan-clustering`        |
| `fix/`      | Bug fixes                                | `fix/span-pagination-overflow`   |
| `chore/`    | Tooling, CI, config, deps                | `chore/pin-phoenix-client`       |
| `refactor/` | Code restructuring (no behavior change)  | `refactor/orchestrator-split`    |
| `docs/`     | Documentation only                       | `docs/quickstart-windows`        |
| `test/`     | Test additions / restructuring           | `test/golden-dataset-coverage`   |

## Code Style

The architectural rules — code-first evaluators, no data egress, human-in-the-loop, Phoenix SDK for writes / MCP for reads, pinned Phoenix versions — are summarized in the README. Read those before opening a non-trivial PR.

CI rejects suppressions (`# noqa`, `# type: ignore`, `// eslint-disable`, `as any`). If a rule fires, fix the root cause.

### External-API failures

Anything that talks to Phoenix or Gemini raises a typed exception from [nengok/errors.py](../nengok/errors.py), not a bare `RuntimeError`. The CLI catches `NengokError` once and dispatches to a per-class hint, so the operator sees `Error (missing-api-key): ...` with the env var to set, or `Error (gemini-quota): ...` with the retry delay and quotaId, instead of a traceback. When you add a new call site, follow the same pattern: pick the closest existing class (`MissingApiKeyError`, `OptionalDependencyError`, `BaselinePromptError`, `AgentRunnerLoadError`, `PhoenixConnectionError`, `PhoenixProjectNotFoundError`), include the exact fix in the message (env var name, config field, install command, or URL), and pass structured context as keyword args so the dispatcher can render it. Add a new subclass only if no existing one fits, and register a label for it in `nengok.cli._error_label`.

### Redacting span text before it leaves the process

Every Gemini call site that embeds span content (input/output values, exemplar bodies) and every on-disk artifact that quotes a trace must pass the text through `Redactor` first. The defaults scrub emails, Google and AWS keys, bearer tokens, `password=`/`secret=` fields, credit-card numbers, SSNs, US phone numbers, IPv4 and IPv6 addresses. The full threat model lives in [docs/security.md](../docs/security.md).

When you add a new stage that ships span text outward, accept an optional `redactor: Redactor | None` on the dataclass and resolve it with `self.redactor or Redactor.from_config(self.config)` inside the call. The orchestrator constructs one `Redactor` per cycle from `NengokConfig` and threads it into every stage; tests can override it by passing a custom instance. Disable redaction only with `config.redaction_enabled = false` and only when you have a stricter scrubber upstream. The `config.redactor_callable` escape hatch (dotted path) replaces the default rules with a user-supplied function for teams that already maintain an in-house scrubber.

### Tests that need an optional extra

SDK CI runs two pytest jobs. `test` installs `[dev]` only, on Python 3.11 and 3.12 across `ubuntu-latest` and `windows-latest` (four shards), so we catch the case where core SDK code accidentally requires an optional dependency or breaks on a different filesystem. `test-full-extras` installs `[dev,gemini,phoenix]` on Python 3.12 and runs the same suite so the Gemini wrapper and Phoenix dataclass tests actually exercise the upstream types.

A test file that imports `google.genai`, `phoenix.client.*`, or any other module from an optional extra at module top breaks collection in the minimal-deps job. Guard the import with `pytest.importorskip` so the test skips cleanly there and runs for real in the full-extras job:

```python
import pytest

genai_errors = pytest.importorskip(
    "google.genai.errors",
    reason="google-genai not installed; this test needs the gemini extra.",
)

from nengok.utils.gemini import call_gemini
```

The `tests/**` per-file ignore in `pyproject.toml` allows imports below an `importorskip` call (otherwise ruff E402 would fire). Outside `tests/`, imports stay at the top. The relaxation is test-only and is the project's one structural exception to the no-suppressions rule above.

The full-extras job also runs `python -c "import google.genai.errors; import phoenix.client.resources.experiments"` before pytest, so if either extra ever silently goes empty (someone deletes a package from the extra in `pyproject.toml`), the job fails loudly instead of letting the wrapper tests skip themselves out of existence.

### Security and packaging gates

SDK CI runs three more jobs that gate the production wheel:

`bandit` scans `nengok/` against the config in `[tool.bandit]` (in `pyproject.toml`). The config skips three rule classes with documented rationale: `B101` (asserts used for type narrowing, since `-O` is not a supported deployment path), `B105` (string literals that match `*_token` are env-var names, not credentials), and `B310` (urlopen targets are operator-supplied URLs parsed at config-load). `tests/` and `phoenix_harness/` get a separate scan with `--skip B101,B104,B106,B108` for legitimate test patterns. Adding a new assert, urlopen, or `*_token` literal in production code is fine; bandit will not flag it. Adding a real secret to source is not fine. Keep credentials in env vars and the config TOML.

`pip-audit` gates the dependency tree against known CVEs. The CI job uninstalls the editable nengok install before auditing, then runs `pip-audit` with no flags. pip-audit treats the editable skip as a fatal log on Linux runners, so removing nengok from the active environment is the only portable way to keep the gate honest about dependency CVEs without false failures on the unpublished package itself. If a transitive dependency picks up a CVE, bump the offending package in `pyproject.toml` rather than suppressing.

`smoke-install` builds the wheel via `python -m build`, installs it in a clean venv, and runs `nengok --version` plus `nengok init --help`. This catches packaging regressions the editable install hides, such as a missing `[project.scripts]` entry or a forgotten data file in the hatch include list.

### Frontend tests

`frontend/` has a Vitest + React Testing Library suite under `frontend/src/pages/__tests__/`. Page tests render through the `renderWithProviders` helper in [frontend/src/test/renderWithProviders.tsx](../frontend/src/test/renderWithProviders.tsx), which wraps the component in a fresh `QueryClient`, a `MemoryRouter`, and the `LayoutProvider`. API modules under `frontend/src/api/` are mocked with `vi.spyOn(...)` so tests never hit a backend.

Run them with `npm test` (one-shot) or `npm run test:watch`. Frontend CI runs the same `npm test` command in a separate `Vitest` job alongside the existing lint and build jobs.

## Phoenix API Cheatsheet

The Phoenix surface Nengok actually calls. Use this as the canonical reference when writing or reviewing code that touches `nengok/phoenix/`. MCP tools are reliable for reading traces, spans, and sessions; dataset creation and experiment execution go through the Python SDK because it has been more stable for programmatic workflows.

```python
from phoenix.client import Client
from phoenix.client.experiments import run_experiment
from phoenix.evals import create_evaluator, ClassificationEvaluator, LLM
from phoenix.otel import register, SpanAttributes

# Tracing
register(project_name="...", auto_instrument=True)

# Read spans
px_client = Client()
spans = px_client.spans.get_spans(project_identifier="...", limit=200)

# Create dataset
dataset = px_client.datasets.create_dataset(name="...", inputs=[...], outputs=[...])

# Run experiment
experiment = px_client.experiments.run_experiment(
    dataset=dataset, task=task_fn, evaluators=[...],
    experiment_name="...", dry_run=3  # sanity check first
)

# Add evals to existing experiment
px_client.experiments.evaluate_experiment(experiment=experiment, evaluators=[...])

# Code evaluator
@create_evaluator(name="check", kind="code")
def my_eval(output, expected) -> bool: ...

# LLM-as-Judge evaluator (mustache templates)
judge = ClassificationEvaluator(
    name="correctness",
    prompt_template="...{{input}}...{{output}}...",
    llm=LLM(provider="google", model="gemini-3-flash-preview"),
    choices={"correct": 1.0, "incorrect": 0.0},
)
```

## Naming Conventions

### Python (`nengok/`, `sample_agent/`, `phoenix_harness/`, `tests/`)

| Kind | Convention | Example |
|---|---|---|
| Variable | `snake_case` | `cluster_id`, `span_count` |
| Function | `snake_case` | `def get_anomalous_spans(...)` |
| Module / file | `snake_case.py` | `prompt_proposer.py`, `experiment_runner.py` |
| Package / directory | `snake_case/` | `nengok/core/observer/`, `nengok/phoenix/` |
| Class (Pydantic model, service, evaluator) | `PascalCase` | `Cluster`, `RootCauseHypothesis`, `ExperimentRunner` |
| Enum class | `PascalCase` | `ClusterStatus`, `EvaluatorKind` |
| Enum member | `UPPER_SNAKE_CASE` | `ClusterStatus.OPEN`, `EvaluatorKind.CODE` |
| Constant | `UPPER_SNAKE_CASE` | `DEFAULT_SPAN_LIMIT`, `PASS_RATE_THRESHOLD` |
| Private helper | `_leading_underscore` | `def _normalize_attributes(...)` |
| Type alias | `PascalCase` | `SpanId = str` |

**Pydantic schema suffixes**: `*Create`, `*Update`, `*Response`, `*ListResponse`. Example: `ClusterResponse`, `ApprovalCreate`.

### TypeScript / React (`frontend/`)

| Kind | Convention | Example |
|---|---|---|
| Variable | `camelCase` | `currentCluster`, `experimentResult` |
| Function | `camelCase` | `function fetchClusters(...)` |
| React component | `PascalCase` | `ClusterCard`, `ApprovalPanel` |
| Component file | `PascalCase.tsx` | `ClusterCard.tsx`, `ApprovalPanel.tsx` |
| Helper / non-component file | `camelCase.ts` | `clusterHelpers.ts`, `apiClient.ts` |
| Hook | `camelCase` starting with `use` | `useClusters`, `useExperiment` |
| Type / interface | `PascalCase` | `Cluster`, `Experiment` |
| Enum | `PascalCase` (members `UPPER_SNAKE_CASE`) | `ClusterStatus.OPEN` |
| Constant | `UPPER_SNAKE_CASE` | `POLL_INTERVAL_MS`, `MAX_TRACES_DISPLAYED` |

**Type-only imports** must use the `type` keyword:

```ts
import type { Cluster } from "../types/cluster";
import { type Cluster, clusterApi } from "../api/clusters";
```

## Commenting Standards

**Default: write no comment.** Well-named code is self-documenting. Only add a comment when removing it would confuse a future reader.

### What NOT to comment

| Anti-pattern | Why |
|---|---|
| `# increments counter` above `counter += 1` | Restates what the code does. |
| `// loop over clusters` above `for (const c of clusters)` | Same. |
| `# added for issue #42` / `// fix for the bug from PR 87` | Belongs in the commit message or PR description. |
| `# TODO: refactor someday` | Either do it or open an issue. |
| `// removed deprecated branch` next to no code | The diff tells the story. |
| Multi-paragraph essays describing what a function does | Use a docstring; keep it short. |

### When a comment is justified

1. **A non-obvious constraint or invariant** — e.g. "We use the SDK for writes and MCP for reads because MCP's dataset-creation tool has been flaky on multi-row inputs."
2. **A subtle bug fix** the code alone doesn't explain.
3. **A workaround for an external system** — e.g. a Phoenix client quirk.
4. **A pointer to a related file or doc**, when navigation wouldn't make the connection obvious.

If you can rename a variable or extract a function instead of writing a comment, do that.

### Python: docstring-style only

```python
def cluster_failures(spans: list[Span], min_cluster_size: int = 3) -> list[Cluster]:
    """
    Group anomalous spans into named failure clusters.

    Uses a two-pass approach: a coarse text-similarity pass, then a
    Gemini sub-cluster pass that separates "same symptom, different
    cause" failures before fix generation.
    """
    ...
```

Module-level docstrings are fine for files whose purpose isn't obvious from the filename.

### TypeScript: JSDoc on non-obvious components and functions

```ts
/**
 * Side-by-side diff of the current prompt vs. the proposed fix.
 * Highlights added/removed lines and renders mustache placeholders
 * (`{{input}}`, `{{output}}`) with distinct styling so reviewers can
 * tell template variables apart from prose.
 */
export function PromptDiff({ before, after }: Props) { ... }
```

## Commit Messages

```
feat: add HDBSCAN first-pass clustering
fix: paginate span retrieval to avoid 5k-row overflow
chore: pin arize-phoenix-client to 1.16.0
docs: clarify human-in-the-loop guarantees
docs(sdk): document the dry-run safeguard
test: golden-dataset regression coverage for weather tool
```

Format: `<type>(<optional scope>): <short description>`. Keep the first line under 72 chars.

### CI/CD behavior by commit type

Commits prefixed with `docs:` or `docs(<scope>):` skip CI entirely.

| Commit prefix | CI runs | Deploy runs |
|---|---|---|
| `feat:`, `fix:`, `refactor:`, `chore:`, `test:` | Yes (on changed paths only) | Yes (on `main` push, where applicable) |
| `docs:` or `docs(scope):` | **Skipped** | **Skipped** |

Only use `docs:` when your commit **exclusively** changes documentation.

## Pull Requests

1. Open PRs against `main`.
2. Use the PR template.
3. Keep PRs focused — one feature or fix per PR.
4. Cross-cutting? Still ONE PR — the monorepo is the point.
5. Squash-merge when approved.

## Path-Filtered Workflows

CI workflows trigger based on which directories changed:

- `nengok/**`, `pyproject.toml`, `tests/**` → `SDK CI` runs
- `frontend/**` → `Frontend CI` runs
- `sample_agent/**` → `Sample Agent CI` runs (lint + smoke test)
- `phoenix_harness/**` → `Phoenix Harness` runs (live integration tests, gated by a repo secret)
- A tagged release (`v*.*.*`) → `Publish` runs and pushes to PyPI

This keeps CI fast on day-to-day work while still giving the harness a place to live.
