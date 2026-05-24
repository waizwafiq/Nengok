# Contributing to Nengok

Thanks for your interest in Nengok. The SDK is the product (the dashboard is a thin local UI on top of it), so most contributions should land in `nengok/`.

This is a monorepo: the SDK, the dashboard frontend, the demo agent, and the Phoenix integration harness all live in one history. Cross-cutting changes ship as one PR.

## Getting Set Up

### Prerequisites

- Python 3.11+ (`python --version`)
- Node 22+ (only if you touch the dashboard frontend)
- A reachable Arize Phoenix instance (Phoenix Cloud, self-hosted, or `phoenix serve` locally)
- A Google AI Studio API key for Gemini

### 1. Clone the repo

```bash
git clone https://github.com/waizwafiq/Nengok.git nengok-codebase
cd nengok-codebase
```

Run every command from this directory (the repo root). `pyproject.toml` lives here; the `nengok/` subdirectory is the Python package and does not contain a manifest. If you `cd` one level too deep, `pip install` prints `does not appear to be a Python project`.

### 2. Install the SDK in editable mode

Two ways to do this. The `uv` path is roughly 10x faster on a cold install and does not require a system Python 3.11+.

#### Fast path: `uv`

[`uv`](https://docs.astral.sh/uv/) is a drop-in replacement for `pip` + `venv` that ships managed Python builds and a shared wheel cache.

```bash
# One-time: install uv (skip if already on PATH)
pip install --user uv

# Download a managed CPython 3.12 (no admin, no PATH changes)
python -m uv python install 3.12

# Create the venv and install everything
python -m uv venv --python 3.12
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m uv pip install -e ".[dev]"
```

Cold install: under 10 seconds.

If `uv` is not on your PATH after `pip install --user uv`, keep invoking it as `python -m uv ...` or run `python -m uv python update-shell` once.

#### Stock path: `pip`

Needs Python 3.11+ already installed and on your PATH.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Cold install: 2 to 5 minutes on Windows because `uvicorn[standard]` pulls in a few Rust-built dependencies.

You end up with Nengok in editable mode plus the dev extras (`ruff`, `pytest`, `mypy`).

### 3. Configure environment

Copy `.env.example` to `.env` and fill in:

```bash
cp .env.example .env
```

```
PHOENIX_BASE_URL=http://localhost:6006
PHOENIX_API_KEY=...
GOOGLE_API_KEY=...
NENGOK_ARTIFACTS_DIR=./artifacts
```

### 4. Start a local Phoenix (optional, for end-to-end work)

```bash
pip install arize-phoenix
phoenix serve
```

Phoenix UI: <http://localhost:6006>.

### 5. Run the sample agent to generate traces

```bash
python -m sample_agent.agent
```

This boots the Travel Planner demo and emits OpenInference traces to your Phoenix instance.

### 6. Run a Nengok cycle

```bash
nengok init --phoenix-url http://localhost:6006
nengok run
```

### 7. Launch the dashboard (optional)

```bash
nengok dashboard
# FastAPI server at http://localhost:8765
# Vite dev server (if running) proxies to it at http://localhost:5173
```

For frontend development:

```bash
cd frontend
npm install
npm run dev
```

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
