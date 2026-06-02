# Nengok

> Phoenix shows you what's wrong. **Nengok fixes it.**

[![PyPI](https://img.shields.io/badge/pypi-v0.1.0-blue)](https://pypi.org/project/nengok/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)
[![Built on](https://img.shields.io/badge/built%20on-Arize%20Phoenix-orange)](https://github.com/Arize-ai/phoenix)

Nengok (Malay: *"to watch over"*) is a pip-installable SDK that **autonomously detects, diagnoses, and fixes silent failures** in AI agents. It connects to *your* Arize Phoenix instance, samples production traces, clusters failure patterns, generates regression tests from real failures, runs controlled experiments to verify fixes, and presents verified solutions for human approval.

**Trace data never leaves your infrastructure.** Nengok runs locally next to your Phoenix instance, calls your Gemini key, and writes fix artifacts to your local filesystem.

```
$ pip install nengok
$ nengok init --phoenix-url http://localhost:6006
$ nengok run

Observer:  200 spans -> 16 anomalies -> 16 new after dedup
Diagnoser: 3 clusters with hypotheses
Fixer:     cluster 'flights-schema-drift' -> baseline 25% -> fix 100% (golden: no regression)
Verifier:  PASSED -> artifacts/flights-schema-drift/

Cycle complete: 3 clusters detected, 1 fix proposed, 0 escalations.
Run `nengok dashboard` to review and approve.
```

## Why Nengok?

Every AI agent in production loses money through **confident wrong answers**. HTTP 200, no error log, just a quietly hallucinated hotel name or a date parsed from the wrong schema. The fix loop is brutal:

1. A user complains (days or weeks later).
2. A senior engineer digs through trace logs.
3. They reproduce, write an eval, hand-craft a fix.
4. They never write a regression test, so the same class fails again next month.

Phoenix gives you the observability layer. Nengok adds the **autonomous remediation loop on top**:

```
   Observer  ->  Diagnoser  ->  Fixer  ->  Verifier
       |             |            |           |
   Pull anomalous  Cluster +    Generate   Pass/fail
   spans from     hypothesize  tests +    gate +
   Phoenix        root cause   experiment artifact
                                          output
```

Each cycle takes minutes instead of hours, every fix becomes a permanent regression test, and a human approves every change before anything ships.

## Features

- **Plug-and-play with Phoenix.** Works with Phoenix Cloud, self-hosted Phoenix, or `phoenix serve` running on your laptop.
- **Two-stage failure filtering.** Anomaly query at the SDK layer, then deduplication against previously-seen span IDs. You never re-process healthy traffic.
- **Two-pass clustering** *(stretch)*. HDBSCAN on trace embeddings, then Gemini sub-clusters by hypothesized root cause so "same symptom, different cause" failures get separated.
- **Code-first, LLM-second evaluators.** Structural checks are programmatic; only subjective dimensions (coherence, intent match) reach an LLM-as-Judge. Mitigates the well-documented position/verbosity bias of LLM judges.
- **A/B experiments via Phoenix.** Baseline vs. fix prompt, full per-case breakdown, dry-run safeguard.
- **Human approval gate.** Every fix lands in `artifacts/` and waits for a one-click approve / reject / dismiss in the local dashboard.
- **Zero data egress.** Your traces stay in your Phoenix. Your Gemini key calls Google directly from your machine. Nothing in this loop goes to a Nengok-controlled endpoint.

## Stack

- Python 3.11+ for the SDK and engine, TypeScript for the dashboard.
- Gemini 3.1 for reasoning (`gemini-3.1-pro-preview`) and LLM-as-Judge (`gemini-3-flash-preview`).
- Google ADK as the agent framework.
- Arize Phoenix for observability (Python SDK + `@arizeai/phoenix-mcp@4.0.13`, CLI).
- FastAPI bundled inside the SDK to serve the dashboard API.
- Vite, React, TypeScript, and Tailwind for the frontend.
- SQLite (default) or any Postgres / MySQL via `DATABASE_URL`, served through `nengok/state/store.py`.
- `pip install nengok` for local use; Cloud Run for the hackathon hosted URL.

## Quickstart

### Prerequisites

- Python 3.11+
- A reachable Phoenix instance ([Phoenix Cloud](https://phoenix.arize.com), self-hosted, or `phoenix serve`)
- A Google AI Studio API key for Gemini

### 1. Install

```bash
pip install nengok
```

Nengok writes cluster state to `~/.nengok/state.db` (SQLite) on first run, so the default install has no database setup step. Point `DATABASE_URL` at Postgres or MySQL when you want shared state across pods; the optional `deploy/local/docker-compose.postgres.yml` and `deploy/local/docker-compose.mysql.yml` files bring a local instance up for backend testing. For local development against this repo, see [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md).

### 2. Configure

```bash
nengok init --phoenix-url http://localhost:6006 --project my-agent
export PHOENIX_API_KEY=...        # if your Phoenix requires auth
export GOOGLE_API_KEY=...
```

`nengok init` writes `~/.nengok/config.toml`. Secrets stay in your environment.

### 3. Run a cycle

```bash
nengok run
```

This executes one full Observer -> Diagnoser -> Fixer -> Verifier pass.

### 4. Watch continuously (optional)

```bash
nengok watch --interval 300
```

### 5. Review and approve

```bash
nengok dashboard
# Opens http://127.0.0.1:8765
```

The dashboard renders every fix-proposed cluster (the proposed prompt diff, the regression dataset, the root-cause analysis) and gives you one-click approve / reject / dismiss.

## Project Layout

```
nengok-codebase/
├── nengok/                # The SDK (pip install nengok)
│   ├── cli.py             # nengok run, watch, dashboard, init
│   ├── config.py
│   ├── core/              # Orchestrator + the four pipeline stages
│   │   ├── observer/
│   │   ├── diagnoser/
│   │   ├── fixer/
│   │   ├── verifier/
│   │   └── evaluators/    # Code-based + LLM-as-Judge
│   ├── phoenix/           # Phoenix SDK + MCP integration
│   ├── server/            # Bundled FastAPI dashboard API
│   └── state/             # SQLite cluster lifecycle
├── frontend/              # Vite + React + TS + Tailwind dashboard
├── sample_agent/          # Travel Planner demo agent (3 injectable failures)
├── phoenix_harness/       # Live integration tests against a real Phoenix
├── golden_dataset/        # Curated cases the Verifier never lets regress
├── tests/                 # Unit tests (fakes, no network)
├── artifacts/             # Fix output (per-cluster prompt + dataset + RCA)
├── deploy/                # Cloud Run image for the hosted-demo URL
├── pyproject.toml
└── README.md
```

## The Demo Scenario

The `sample_agent/` package ships a Travel Planner with three runtime-toggleable failure modes:

| Failure mode | What goes wrong | Effect on the agent |
|---|---|---|
| `flights` | `departure_time` changes from `"14:30"` to `{"hour": 14, "minute": 30}` | Agent emits a malformed itinerary |
| `weather` | Temperature unit silently switches from F to C | Agent suggests a parka for 75 °F weather |
| `hotels` | Endpoint times out 40 % of the time | Agent hallucinates hotel names instead of erroring |

A second sample agent lives under `sample_agent/qa_agent/`. It is a tiny retrieval-augmented Q&A with three injectable failure modes: `retriever` drops the retrieved context, `hallucination` patches the prompt to answer from memory, and `wrong_attribution` rotates snippet ids so the citation no longer matches its body. Nengok can point at it without code changes.

Run the demo with one copy-paste:

```bash
python -m sample_agent.seed --count 5
nengok init --phoenix-url http://localhost:6006 --project travel-planner-agent
nengok run
```

`sample_agent.seed` fires five runs of the Travel Planner with every failure mode injected, then prints the Phoenix project URL. Hand the same project name to `nengok init` and `nengok run` walks the four-stage loop end to end. Run `nengok dashboard` afterwards to approve the verified fix.

## Plug in Your Own Agent

Nengok loads any class that satisfies the `AgentRunner` protocol: a `name` property and a `run(agent_input: dict, prompt: str) -> dict` method. Drop the class in your own package, then point Nengok at it from `~/.nengok/config.toml`:

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
[nengok]
project_identifier = "my-agent"
agent_runner = "my_pkg.runner:MyAgent"
baseline_prompt_path = "my_pkg/prompts/system.md"
```

Then `nengok doctor` confirms the runner imports and the protocol check passes, and `nengok run --project my-agent` cycles against your traces. The bundled `sample_agent/qa_agent/` is a worked example you can copy from.

## Architecture

```
Your Infrastructure
+---------------------------------------------------------------+
|                                                                |
|   $ pip install nengok                                         |
|                                                                |
|   +------------------------------------------------------+    |
|   |                 Nengok SDK                            |    |
|   |                                                       |    |
|   |  +--------+  +----------+  +-------+  +----------+   |    |
|   |  |Observer|->|Diagnoser |->|Fixer  |->|Verifier  |   |    |
|   |  +---+----+  +-----+----+  +---+---+  +----+-----+   |    |
|   +------+-------------+-----------+------------+--------+    |
|          v             v           v            v              |
|     +---------+  +----------+ +-------+ +-----------+         |
|     | Your    |  | Your     | | Your  | | Local     |         |
|     | Phoenix |  | Gemini   | |Phoenix| | artifacts |         |
|     | (read)  |  | key      | |(write)| | + dash    |         |
|     +---------+  +----------+ +-------+ +-----------+         |
|                                                                |
+---------------------------------------------------------------+
                    Nothing leaves this box.
```

## Project Rules

These are non-negotiable for every contribution. See [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md) for the full guide.

- **Code-first, LLM-second evaluators.** Anything objectively verifiable lives in `nengok/core/evaluators/code_evals.py`. LLM-as-Judge is reserved for subjective criteria.
- **No data egress.** Nengok must never send trace data to a third-party endpoint. Period.
- **Human-in-the-loop always.** No code path auto-applies a fix.
- **Phoenix SDK for writes, MCP for reads.** Centralized in `nengok/phoenix/client.py` and `nengok/phoenix/mcp.py`.
- **Pinned Phoenix versions.** `arize-phoenix-client` is pinned in `pyproject.toml`. Do not chase upstream releases mid-cycle.

## Roadmap

- **v0.1 (current):** Closed-loop Observer -> Diagnoser -> Fixer -> Verifier with local artifacts and approval UI.
- **v0.2:** Git MCP integration. Approved artifacts open as PRs automatically.
- **v0.3:** Multi-agent monitoring, event-driven heartbeat, cluster state persistence across cycles.
- **v0.4:** Managed cloud tier (open-core, following the Langfuse playbook). The self-hosted SDK stays the source of truth.

### Out of scope for v0.1

The v0.1 hackathon release intentionally defers:

- Git MCP integration. Approved fixes write to `artifacts/`; opening them as PRs lands in v0.2.
- Event-driven heartbeat cycle. The current loop polls on a fixed 5-minute interval. Event-driven scheduling lands in v0.3.
- Span deduplication across cycles. The demo uses controlled traffic so re-ingest is not a problem.
- Cluster lifecycle persistence across cycles. The loop runs once per demo; persistence lands in v0.3.
- Real-time executive dashboard with historical trends. The pitch video uses a static mockup.
- HDBSCAN clustering pipeline. v0.1 ships Gemini-only clustering; HDBSCAN is a stretch goal.
- Multi-agent monitoring. v0.1 watches a single Travel Planner; multi-agent monitoring lands in v0.3.

## Acknowledgements

Nengok is built on top of [Arize Phoenix](https://github.com/Arize-ai/phoenix) and would not exist without the MCP server, Python SDK, OpenInference instrumentation, and Phoenix Skills published by the Arize team. Nengok automates the workflow Phoenix's own documentation teaches developers to perform by hand.

The clustering and root-cause hypothesis pipeline is informed by Pathak et al. (2025), *Detecting Silent Failures in Multi-Agentic AI Trajectories*, and by the SAGE benchmark on LLM-as-Judge reliability.

## License

[Apache License 2.0](LICENSE).
