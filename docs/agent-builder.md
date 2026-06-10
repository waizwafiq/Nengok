# The ADK triage agent

Every Nengok cycle opens with a triage step before the Observer pulls a single span. The step is an `LlmAgent` from the Google Agent Development Kit (ADK), the agent framework in [Google Cloud's Agent Builder suite](https://cloud.google.com/products/agent-builder), defined in [nengok/agents/triage.py](../nengok/agents/triage.py) and armed with one tool: a `McpToolset` that spawns the Arize Phoenix MCP server (`@arizeai/phoenix-mcp`, pinned to the same version the preflight check uses). The agent inspects the last few minutes of traffic in the configured project through Phoenix MCP tools and returns a verdict: wake the full deterministic pipeline, or let this cycle sleep.

The Diagnoser, Fixer, and Verifier stay deterministic on purpose. The triage gate is the single ADK surface in the loop, and it is load-bearing: when it says skip, the cycle records `skipped_by_triage` and ends without touching Phoenix again.

## Install

```bash
pip install "nengok[adk]"
```

The extra pins `google-adk` to an exact version because the MCP toolset module path has moved between ADK releases. The toolset spawns Node via `npx`, so Node 18+ must be on PATH wherever the loop runs. The demo-recording install line composes the extras and deliberately leaves out the optional `clustering` extra so every model call in the loop is a Gemini call:

```bash
pip install "nengok[gemini,phoenix,adk,tui]"
```

## The verdict

The agent must answer with a single JSON object that validates against `TriageVerdict`:

| Field | Type | Meaning |
|---|---|---|
| `investigate` | bool | Whether the deterministic pipeline should run this cycle. |
| `project` | str | The Phoenix project the Observer should read. |
| `projects` | list of str | On a multi-project install, the subset of projects worth investigating this cycle; the orchestrator narrows the cycle to these. |
| `window_minutes` | int (1 to 240) | The time window the Observer should narrow to. |
| `reason` | str (280 chars max) | One sentence the operator can read in the log. |
| `signals` | list of str | Names of the signals the agent saw firing. |

Unknown fields are rejected (`extra='forbid'`), and a verdict that fails validation is retried once with a fresh session before the cycle falls back. When `investigate` is true, the Observer reads the verdict's project over the verdict's window instead of the configured defaults. The prompt lives in [nengok/agents/triage_prompt.md](../nengok/agents/triage_prompt.md) so prompt edits are reviewable separately from code; it biases the agent toward `investigate = true` under uncertainty, because a missed cluster never gets fixed while a false-positive wake only runs the rule-based anomaly filter that exists anyway.

## Configuration

| Key (TOML) | Env var | Default | What it controls |
|---|---|---|---|
| `triage_enabled` | `NENGOK_TRIAGE_ENABLED` | `true` | Whether the gate runs at all. |
| `triage_model` | `NENGOK_TRIAGE_MODEL` | `gemini-3-flash-preview` | The model behind the `LlmAgent`. Flash, not Pro: the prompt is small and the verdict schema is fixed. |
| `triage_timeout_seconds` | `NENGOK_TRIAGE_TIMEOUT_SECONDS` | `30.0` | Wall-clock budget for the whole triage pass, MCP subprocess spawn included. |
| `triage_lookback_minutes` | `NENGOK_TRIAGE_LOOKBACK_MINUTES` | `15` | The window the agent is asked to inspect, and the fallback verdict's window. |

`nengok run --no-triage` and `nengok watch --no-triage` skip the gate for one invocation without touching config. This is useful when you want the deterministic path on every cycle, for example while bisecting an Observer or Diagnoser problem that has nothing to do with triage.

## Fallback behavior

A flaky agent call must not break the working loop. If the triage pass fails for any reason (schema violation after the retry, timeout, MCP subprocess death, Gemini error, missing extra), the orchestrator logs the exception at WARNING and proceeds as if the verdict had been `investigate = true` over the configured project and lookback, with `reason = "triage_fallback"`.

Every cycle emits one INFO line with `event='triage_decided'` carrying `triage_path` (`adk` or `fallback`), `investigate`, `project`, `window_minutes`, and `reason`. Grep for `triage_path=` to confirm which path ran. Three Prometheus series track the same story when `metrics_enabled = true`: `nengok_triage_total{path,outcome}`, `nengok_triage_duration_seconds`, and `nengok_triage_errors_total{error_class}`. The `/health` endpoint reports `triage_adk_ratio`, the in-process share of decisions that took the ADK path; a ratio sliding toward zero in a `nengok watch` process means the agent is failing and every cycle is riding the fallback.

When `triage_enabled` is true but the gate cannot run at all (the `adk` extra is not installed, or `npx` is missing), the orchestrator warns once at startup and runs without triage for the rest of the process.

## Troubleshooting

Triage logs `triage_path=fallback` on every cycle: run `nengok doctor`. The triage probe prints the disabled reason verbatim, which separates "turned off in config" from "the adk extra is missing" from "npx is not on PATH". If the probe is green, read the WARNING line above each fallback; it carries the exception class and traceback.

Cloud Run boot fails after a triage redeploy: check that Node made it into the runtime image with `docker run --rm <image> npx --version`. The Node install line lives in the runtime stage of [deploy/Dockerfile](../deploy/Dockerfile); the frontend build stage having Node is not enough, because `McpToolset` spawns `npx` at runtime.

The first cycle on a cold instance is slow: the Dockerfile pre-warms the `npx` cache with the pinned `@arizeai/phoenix-mcp` package at build time. If that layer was skipped or the pin changed, the first triage pays the package download once.

## Credentials

The triage agent introduces no new credential boundary. The Phoenix base URL and API key reach the MCP subprocess through environment variables, the same channel the preflight check in [nengok/phoenix/mcp.py](../nengok/phoenix/mcp.py) uses, so the key never appears in a process argument list. The Gemini call rides whatever backend the rest of the loop uses: an AI Studio key locally, or Vertex AI Application Default Credentials on Cloud Run. See [docs/security.md](security.md) for the wider threat model.
