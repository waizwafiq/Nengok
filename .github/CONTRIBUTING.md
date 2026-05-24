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
python -m uv pip install -e ".[dev,phoenix]"
```

**macOS / Linux:**

```bash
pip install --user uv
python -m uv python install 3.12
python -m uv venv --seed --python 3.12
source .venv/bin/activate
python -m uv pip install -e ".[dev,phoenix]"
```

If `uv` is not on your PATH after `pip install --user uv`, keep invoking it as `python -m uv ...` or run `python -m uv python update-shell` once.

**Why `--seed`?** A bare `uv venv` does not install `pip` inside the venv. After activation, running plain `pip install <pkg>` then falls back to your *system* Python's pip and installs the package outside the venv, where Nengok cannot see it. `--seed` puts a real `pip` inside the venv so both `pip install` and `python -m uv pip install` write to the right place.

#### Option B: stock `pip`

Needs Python 3.11+ already installed and on your PATH. Cold install: 2 to 5 minutes on Windows because `uvicorn[standard]` pulls in a few Rust-built dependencies.

**Windows (PowerShell or cmd):**

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev,phoenix]"
```

**macOS / Linux:**

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,phoenix]"
```

You end up with Nengok in editable mode plus the dev extras (`ruff`, `pytest`, `mypy`) and the Phoenix client. Skip the `phoenix` extra only if you are working on internal modules that never touch `nengok.phoenix.client`; `nengok run` will not work without it.

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

### 4. Start a local Phoenix (optional, for end-to-end work)

If you already have Phoenix Cloud or a remote Phoenix, point `PHOENIX_BASE_URL` and `PHOENIX_API_KEY` at it in `.env` and skip this step.

**All platforms** (run in a separate terminal so it stays up):

```bash
pip install arize-phoenix
phoenix serve
```

Phoenix UI: <http://localhost:6006>.

### 5. Generate traces with the sample agent

In a new terminal with the venv activated, run the Travel Planner demo a few times with all failure modes injected:

**Windows:**

```bat
.venv\Scripts\activate
python -m sample_agent.agent --inject all
```

**macOS / Linux:**

```bash
source .venv/bin/activate
python -m sample_agent.agent --inject all
```

Run that command three or four times. The `--inject all` flag turns on the three demo failure modes (flights schema drift, weather unit mismatch, hotels timeout); each invocation flips the mock tool outputs into their broken shapes, and the clusterer needs roughly three before it can name a pattern. Without `--inject all`, the agent runs cleanly and the clusterer has nothing to bite on.

Heads up: `sample_agent/agent.py`'s `build_itinerary` is currently a stand-in. It calls Python mock tools directly and does not yet make a real Gemini call, so `phoenix.otel.register(auto_instrument=True)` has nothing to wrap. The OTel exporter starts up but emits no spans, and Phoenix will not auto-create the `travel-planner-agent` project from these runs alone. Wiring a real LLM call into `build_itinerary` is tracked work; until then, `nengok run` against the project will 404. If you want to exercise the full Observe -> Diagnose -> Fix -> Verify loop today, either land that LLM call or seed the project with spans from another instrumented script.

If the agent prints `WARNING: PHOENIX_BASE_URL is not set`, your `.env` is missing or you are running from the wrong directory.

### 6. Run a Nengok cycle

```bash
nengok init --phoenix-url http://localhost:6006 --project travel-planner-agent
nengok run
```

`nengok init` writes config to `~/.nengok/config.toml`. `--phoenix-url` is required; `--project` defaults to the literal string `"default"` if you omit it, so pass `--project travel-planner-agent` to match the sample agent. If your Phoenix needs auth, add `--api-key <key>`; otherwise `nengok run` falls back to `PHOENIX_API_KEY` from your `.env` at request time. (Today the CLI does not read `PHOENIX_BASE_URL` or `NENGOK_PROJECT` from `.env` — only `PHOENIX_API_KEY` is picked up later at runtime.)

If `nengok run` reports `404 Not Found` on the spans endpoint, the Phoenix project does not exist yet. The current `sample_agent` stub does not emit spans (see step 5), so a fresh Phoenix install will hit this until you wire a real LLM call into `build_itinerary` or seed the project from another instrumented script.

### 7. Launch the dashboard (optional)

```bash
nengok dashboard --no-browser
# FastAPI server at http://localhost:8765
# Vite dev server (if running) proxies to it at http://localhost:5173
```

The FastAPI server only mounts the React bundle at `/` when a pre-built copy exists in `frontend/dist/`. If you haven't built the frontend, hitting <http://localhost:8765> returns 404, so `--no-browser` keeps the CLI from auto-opening that tab.

For frontend development, in a separate terminal:

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

Then visit <http://localhost:5173>. Vite proxies `/api` calls back to the FastAPI server, so keep `nengok dashboard --no-browser` running in another terminal.

For single-port serving (no Node at runtime), build the bundle once with `npm run build` from `frontend/`. After that, `nengok dashboard` serves the app at <http://localhost:8765> directly and the `--no-browser` flag is no longer needed.

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
