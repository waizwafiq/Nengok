# Nengok

> Phoenix shows you what's wrong. **Nengok fixes it.**

[![PyPI](https://img.shields.io/badge/pypi-v0.1.0-blue)](https://pypi.org/project/nengok/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)
[![Built on](https://img.shields.io/badge/built%20on-Arize%20Phoenix-orange)](https://github.com/Arize-ai/phoenix)

Nengok (Malay: *"to watch over"*) is a pip-installable SDK that **autonomously detects, diagnoses, and fixes silent failures** in AI agents. It connects to *your* Arize Phoenix instance, samples production traces, clusters failure patterns, generates regression tests from real failures, runs controlled experiments to verify fixes, and presents verified solutions for human approval. Every cycle opens with an `LlmAgent` ([nengok/agents/triage.py](nengok/agents/triage.py)) built on the Agent Development Kit (ADK), the agent framework in Google Cloud's Agent Builder suite, that reads recent traffic through the Arize Phoenix MCP server (`McpToolset` running `@arizeai/phoenix-mcp`) and decides whether the full pipeline should wake. Diagnosis runs Gemini 3.1 Pro via `google-genai` (an AI Studio key locally, Vertex AI on Cloud Run), and the hosted demo lives on Cloud Run.

**Trace data never leaves your infrastructure.** Nengok runs locally next to your Phoenix instance, calls your Gemini key, and writes fix artifacts to your local filesystem.

```
$ pip install "nengok[gemini,phoenix,adk]"
$ nengok init --phoenix-url http://localhost:6006
$ nengok run

Triage:    investigate (adk) -> error burst in 'flights' over the last 15m
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
   Triage    ->   Observer  ->  Diagnoser  ->  Fixer  ->  Verifier
      |               |             |            |           |
   ADK agent      Pull anomalous  Cluster +    Generate   Pass/fail
   reads Phoenix  spans from     hypothesize  tests +    gate +
   via MCP,       Phoenix        root cause   experiment artifact
   wakes the loop                                        output
```

Each cycle takes minutes instead of hours, every fix becomes a permanent regression test, and a human approves every change before anything ships.

## Features

- **Plug-and-play with Phoenix.** Works with Phoenix Cloud, self-hosted Phoenix, or `phoenix serve` running on your laptop.
- **ADK triage gate.** An `LlmAgent` armed with Phoenix MCP tools inspects recent traffic at the head of every cycle and decides whether the full pipeline is worth waking. If the agent errors, the cycle falls back to the rule-based anomaly filter; pass `--no-triage` to skip the gate entirely.
- **Two-stage failure filtering.** Anomaly query at the SDK layer, then deduplication against previously-seen span IDs. You never re-process healthy traffic.
- **Clusters with a memory.** A recurring failure mode lands in its existing cluster row instead of minting a new one per cycle. An approved fix that regresses escalates the cluster and fires a notification; rejected and dismissed clusters re-accrete silently instead of re-alerting.
- **More than one agent per install.** List several Phoenix projects in `project_identifiers` and a single cycle observes them all. When two agents fail for the same upstream reason, the cross-agent linker confirms the pair and both cluster pages show an "Also affects" panel.
- **Reviewer feedback becomes signal.** Reject and dismiss decisions (optionally tagged `duplicate_cluster`, `mixed_root_causes`, or `not_a_failure`) replay into the next cycle's clusterer prompt, and `nengok improve` reads the last 30 days of outcomes to propose a clustering prompt amendment that only a human can activate.
- **Code-first, LLM-second evaluators.** Structural checks are programmatic; only subjective dimensions (coherence, intent match) reach an LLM-as-Judge. Mitigates the well-documented position/verbosity bias of LLM judges.
- **A/B experiments via Phoenix.** Baseline vs. fix prompt, full per-case breakdown, dry-run safeguard.
- **Human approval gate.** Every fix lands in `artifacts/` and waits for a one-click approve / reject / dismiss in the local dashboard.
- **Zero data egress.** Your traces stay in your Phoenix. Your Gemini key calls Google directly from your machine. Nothing in this loop goes to a Nengok-controlled endpoint.

## Stack

- Python 3.11+ for the SDK and engine, TypeScript for the dashboard.
- Gemini 3.1 for reasoning (`gemini-3.1-pro-preview`) and LLM-as-Judge (`gemini-3-flash-preview`).
- ADK `LlmAgent` ([nengok/agents/triage.py](nengok/agents/triage.py)) gates every cycle through the Arize Phoenix MCP server (`McpToolset` → `@arizeai/phoenix-mcp`). ADK is the agent framework in Google Cloud's Agent Builder suite. Diagnosis runs Gemini 3.1 Pro via `google-genai`, against an AI Studio key locally or Vertex AI on Cloud Run.
- Arize Phoenix for observability (Python SDK + `@arizeai/phoenix-mcp@4.0.13`, CLI).
- FastAPI bundled inside the SDK to serve the dashboard API.
- Vite, React, TypeScript, and Tailwind for the frontend.
- SQLite (default) or any Postgres / MySQL via `DATABASE_URL`, served through `nengok/state/store.py`.
- `pip install nengok` for local use; the hosted demo dashboard runs on Cloud Run at [nengok-dashboard-863822470060.asia-southeast1.run.app](https://nengok-dashboard-863822470060.asia-southeast1.run.app).

## Quickstart

### Prerequisites

- Python 3.11+
- Node.js 18+ with `npx` on PATH (the triage gate spawns the Phoenix MCP server as a subprocess)
- A reachable Phoenix instance ([Phoenix Cloud](https://phoenix.arize.com), self-hosted, or `phoenix serve`)
- A Gemini API key with billed quota, or Vertex AI access. A full cycle makes 40 to 60 Gemini calls, so a free-tier key's daily limit will not finish one.

### 1. Install

```bash
pip install "nengok[gemini,phoenix,adk]"
```

Nengok writes cluster state to `~/.nengok/state.db` (SQLite) on first run, so the default install has no database setup step. Point `DATABASE_URL` at Postgres or MySQL when you want shared state across pods; the optional `deploy/local/docker-compose.postgres.yml` and `deploy/local/docker-compose.mysql.yml` files bring a local instance up for backend testing. For local development against this repo, see [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md).

### 2. Configure

```bash
nengok init --phoenix-url http://localhost:6006 --project my-agent
export PHOENIX_API_KEY=...        # if your Phoenix requires auth
export GOOGLE_API_KEY=...
```

`nengok init` writes `~/.nengok/config.toml`. Secrets stay in your environment. Every config field is documented with its env var and default in [docs/configuration.md](docs/configuration.md).

### 3. Run a cycle

```bash
nengok run
```

This executes one full Observer -> Diagnoser -> Fixer -> Verifier pass. The install line above includes the `adk` extra, so the cycle opens with the triage agent described in [docs/agent-builder.md](docs/agent-builder.md); pass `--no-triage` to skip it.

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

If you operate Nengok over SSH and would rather stay in the terminal, install the optional TUI extra and run `nengok review` in the same session:

```bash
pip install "nengok[tui]"
nengok review
```

The TUI hits the same FastAPI routes the browser uses, and every decision lands in the same `nengok_approvals` table tagged with `source='tui'`. See [docs/tui-review.md](docs/tui-review.md) for keybindings and the audit-log contract.

## Project Layout

```
nengok-codebase/
├── nengok/                # The SDK (pip install nengok)
│   ├── cli.py             # nengok run, watch, dashboard, review, init
│   ├── config.py
│   ├── core/              # Orchestrator + the four pipeline stages
│   │   ├── observer/
│   │   ├── diagnoser/
│   │   ├── fixer/
│   │   ├── verifier/
│   │   └── evaluators/    # Code-based + LLM-as-Judge
│   ├── phoenix/           # Phoenix SDK + MCP integration
│   ├── server/            # Bundled FastAPI dashboard API
│   └── state/             # Multi-backend cluster lifecycle (SQLite default; Postgres or MySQL via DATABASE_URL)
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

A second sample agent lives under `sample_agent/qa_agent/`. It is a tiny retrieval-augmented Q&A with four injectable failure modes: `retriever` drops the retrieved context, `hallucination` patches the prompt to answer from memory, `wrong_attribution` rotates snippet ids so the citation no longer matches its body, and `flights_schema` rides the same mock flights API as the Travel Planner so the cross-agent linker has a shared upstream failure to find. Nengok can point at it without code changes.

Run the demo with one copy-paste:

```bash
pip install "nengok[gemini,phoenix,adk,tui]"
python -m sample_agent.seed --count 5
nengok init --phoenix-url http://localhost:6006 --project travel-planner-agent
nengok run
```

`sample_agent.seed` fires five runs of the Travel Planner with every failure mode injected, then prints the Phoenix project URL. Hand the same project name to `nengok init` and `nengok run` opens with the ADK triage agent, then walks the four-stage loop end to end. Run `nengok dashboard` afterwards to approve the verified fix. That install line is the one the demo recording uses: it skips the optional `clustering` extra on purpose, so every model call in the loop is a Gemini call.

## Notifications

When a fix is ready for review, Nengok can push a notification so you don't have to poll the dashboard. The notifier layer is a generic protocol — Slack ships as the built-in option, but any channel can be wired in.

### Built-in: Slack

```bash
pip install "nengok[slack]"
```

```bash
# .env
NENGOK_NOTIFIERS=slack
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
NENGOK_SLACK_CHANNEL_ID=C123XXXXXX
NENGOK_SLACK_DASHBOARD_URL=http://localhost:8765
```

Your Slack app needs the `chat:write`, `users:read`, and `users:read.email` bot scopes. When the Verifier passes, Nengok posts a message with the cluster name, pass-rate delta, and **Approve / Reject / Dismiss** buttons. The reviewer's real name and email are resolved via `users.info` before the decision is recorded — anonymous approvals are not accepted.

Set `NENGOK_NOTIFIER_DRY_RUN=true` to preview message layout without enabling approval authority. For full setup instructions and a test script, see [`docs/slack-integration-testing.md`](docs/slack-integration-testing.md).

### Plug in your own notifier

Implement the `Notifier` protocol and register it by dotted path:

```python
# my_pkg/notifier.py
from nengok.notifiers.protocol import NotifierResult
from nengok.notifiers.events import FixProposedEvent, EscalationEvent

class PagerDutyNotifier:
    name = "pagerduty"

    def notify_fix_proposed(self, event: FixProposedEvent) -> NotifierResult:
        ...  # post to PagerDuty
        return NotifierResult(success=True)

    def notify_escalation(self, event: EscalationEvent) -> NotifierResult:
        ...
        return NotifierResult(success=True)
```

```toml
# ~/.nengok/config.toml
[nengok]
notifiers = ["pagerduty"]

[nengok.notifier_registry]
pagerduty = "my_pkg.notifier:PagerDutyNotifier"
```

Multiple notifiers run side-by-side — a failure in one never affects the others. Deduplication is built in: the same event on the same channel fires at most once per cluster, even across repeated `nengok run` cycles.

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
|                                                               |
|   $ pip install nengok                                        |
|                                                               |
|   +-------------------------------------------------------+   |
|   |                      Nengok SDK                       |   |
|   |                                                       |   |
|   |  +--------------------------------+                   |   |
|   |  | Triage: ADK LlmAgent           |                   |   |
|   |  | McpToolset -> @arizeai/        |                   |   |
|   |  | phoenix-mcp -> your Phoenix    |                   |   |
|   |  +---------------+----------------+                   |   |
|   |                  | investigate? project + window      |   |
|   |                  v                                    |   |
|   |  +--------+  +----------+  +-------+  +----------+    |   |
|   |  |Observer|->|Diagnoser |->|Fixer  |->|Verifier  |    |   |
|   |  +---+----+  +-----+----+  +---+---+  +----+-----+    |   |
|   +------+-------------+-----------+------------+---------+   |
|          v             v           v            v             |
|     +---------+  +----------+ +-------+ +-----------+         |
|     | Your    |  | Your     | | Your  | | Local     |         |
|     | Phoenix |  | Gemini   | |Phoenix| | artifacts |         |
|     | (read)  |  | key      | |(write)| | + dash    |         |
|     +---------+  +----------+ +-------+ +-----------+         |
|                                                               |
+---------------------------------------------------------------+
                    Nothing leaves this box.
```

## Project Rules

These are non-negotiable for every contribution. See [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md) for the full guide.

- **Code-first, LLM-second evaluators.** Anything objectively verifiable lives in `nengok/core/evaluators/code_evals.py`. LLM-as-Judge is reserved for subjective criteria.
- **No data egress.** Nengok must never send trace data to a third-party endpoint. Period.
- **Human-in-the-loop always.** No code path auto-applies a fix.
- **Phoenix SDK for writes, MCP for reads.** Centralized in `nengok/phoenix/client.py` and `nengok/phoenix/mcp.py`; the triage agent in `nengok/agents/triage.py` reads through the same MCP server via its ADK toolset.
- **Pinned Phoenix versions.** `arize-phoenix-client` is pinned in `pyproject.toml`. Do not chase upstream releases mid-cycle.

## Roadmap

- **v0.1 (current):** the closed loop end to end. ADK triage gate, Observer -> Diagnoser -> Fixer -> Verifier, cluster identity across cycles, monitoring for several agents at once with cross-agent cluster links, reviewer feedback feeding the clusterer, `nengok improve` retros, local artifacts, and approval from the browser dashboard or the `nengok review` TUI.
- **v0.2:** `TraceBackend` abstraction so Langfuse and raw OTLP can stand in for Phoenix; optional HDBSCAN embedding pre-pass in front of the Gemini clusterer.
- **v0.3:** Git MCP integration (approved artifacts open as PRs), event-driven cycle scheduling with a heartbeat threshold.
- **v0.4:** Plugin architecture for fix strategies, write-back targets, and evaluators; DSPy GEPA and TextGrad fix-generation backends; managed cloud tier (open-core, following the Langfuse playbook). The self-hosted SDK stays the source of truth.
- **v1.0:** EU AI Act audit bundle built on the `nengok export` format.

### Out of scope for v0.1

The v0.1 hackathon release intentionally defers:

- Git MCP integration. Approved fixes write to `artifacts/`; opening them as PRs lands in v0.3.
- A `TraceBackend` abstraction. v0.1 is Phoenix-native; Langfuse and raw OTLP support land in v0.2.
- Event-driven cycle scheduling. The current loop polls on a fixed interval; the heartbeat threshold lands in v0.3.
- HDBSCAN clustering. v0.1 ships the Gemini-only clusterer, with cluster identity and reviewer feedback layered on top. The `clustering` extra exists in `pyproject.toml` but nothing imports it yet.
- Plugin architecture and the DSPy / TextGrad fix backends (v0.4).

## Acknowledgements

Nengok is built on top of [Arize Phoenix](https://github.com/Arize-ai/phoenix) and would not exist without the MCP server, Python SDK, OpenInference instrumentation, and Phoenix Skills published by the Arize team. Nengok automates the workflow Phoenix's own documentation teaches developers to perform by hand.

The clustering and root-cause hypothesis pipeline is informed by Pathak et al. (2025), *Detecting Silent Failures in Multi-Agentic AI Trajectories*, and by the SAGE benchmark on LLM-as-Judge reliability.

## License

[Apache License 2.0](LICENSE).
