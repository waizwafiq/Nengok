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

## Quickstart

### Prerequisites

- Python 3.11+
- A reachable Phoenix instance ([Phoenix Cloud](https://phoenix.arize.com), self-hosted, or `phoenix serve`)
- A Google AI Studio API key for Gemini

### 1. Install

```bash
pip install nengok
```

For local development against this repo, see [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md).

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

Run the demo:

```bash
# 1. Inject all three failures
python -m sample_agent.agent --inject all

# 2. Let Nengok find and fix them
nengok run

# 3. Approve the verified fix
nengok dashboard
```

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

## Acknowledgements

Nengok is built on top of [Arize Phoenix](https://github.com/Arize-ai/phoenix) and would not exist without the MCP server, Python SDK, OpenInference instrumentation, and Phoenix Skills published by the Arize team. Nengok automates the workflow Phoenix's own documentation teaches developers to perform by hand.

The clustering and root-cause hypothesis pipeline is informed by Pathak et al. (2025), *Detecting Silent Failures in Multi-Agentic AI Trajectories*, and by the SAGE benchmark on LLM-as-Judge reliability.

## License

[Apache License 2.0](LICENSE).
