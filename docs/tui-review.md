# Terminal review UI (`nengok review`)

`nengok review` is the Textual-based approval surface for operators who run Nengok on a VPS or a jump host and never want a browser in the loop. It talks to the same FastAPI server the browser dashboard does, writes to the same `nengok_approvals` table, and tags every decision with `source='tui'` so the audit log can attribute the channel.

The browser dashboard ([nengok dashboard](../docs/configuration.md)) is still the right choice when stakeholders want a chart or a shareable URL to paste into a Slack thread. Both ship in v0.1 and read from the same backend, so they always agree on cluster status and fix verdict.

## Install

The TUI is an opt-in extra so a bare install stays slim:

```bash
pip install "nengok[tui]"
```

Add `phoenix` and `gemini` alongside if you also plan to run cycles from the same venv:

```bash
pip install "nengok[tui,phoenix,gemini]"
```

The extra pulls in [Textual](https://textual.textualize.io/) and [Rich](https://rich.readthedocs.io/). Both are Apache 2.0.

## Launching the TUI

Start the FastAPI server first (in tmux, screen, or as a systemd unit):

```bash
nengok dashboard --no-browser
```

In another pane, point `nengok review` at it:

```bash
# Defaults to the dashboard_host / dashboard_port from ~/.nengok/config.toml.
nengok review

# Or target a remote instance over an SSH tunnel.
nengok review --host nengok.internal --port 8080

# Pass a bearer token when the server has dashboard_auth_token set.
nengok review --auth-token "$(cat ~/.nengok/dashboard.token)"
```

The CLI hits `/health` before booting the App. A bad URL fails fast with the same `Error (phoenix-unreachable): ...` message style `nengok doctor` uses.

## Keybindings

| Screen | Key | Action |
|---|---|---|
| Cluster list | `j` / `k` | Move the cursor down / up |
| Cluster list | `Enter` or `o` | Open the highlighted cluster |
| Cluster list | `r` | Reload from the FastAPI server |
| Cluster list | `q` | Quit |
| Cluster detail | `a` | Approve (opens the reason prompt) |
| Cluster detail | `x` | Reject (opens the reason prompt) |
| Cluster detail | `Esc` | Back to the cluster list |
| Approval modal | `Enter` | Submit the decision |
| Approval modal | `Esc` | Cancel without recording |

The cluster detail screen has four tabs: hypothesis (the structured `RootCauseHypothesis` JSON), experiment (per-case baseline vs fix), prompt (the proposed diff with `{{mustache}}` placeholders highlighted), and RCA (the Markdown root-cause document).

## Audit log parity

A TUI approval and a dashboard approval write the same `nengok_approvals` row except for the `source` column:

| Surface | `source` value | Set by |
|---|---|---|
| `nengok dashboard` (browser) | `dashboard` | Default on `POST /api/v1/clusters/{id}/approvals` |
| `nengok review` (TUI) | `tui` | `TuiApiClient.submit_approval` sends `source="tui"` |
| Direct API or scripts | `api` | `POST /api/v1/approvals` legacy route |

`nengok export` carries the field through to both the JSON bundle and the CSV section, so compliance reports can group decisions by channel. The parity test at [tests/test_tui_approval_parity.py](../tests/test_tui_approval_parity.py) is the contract: any change to the approval write path must keep the rows identical apart from `source`.

## Troubleshooting

The CLI raises `OptionalDependencyError` if you forgot to install the extra. Re-run with `pip install "nengok[tui]"` and try again.

If `/health` reports `db_writable: false`, the FastAPI server cannot write to the configured state store. Run `nengok doctor` to identify the failing probe.

When the cluster list shows "No clusters found", the database is empty. Seed traces with `python -m sample_agent.seed --count 5` and run `nengok run` before launching the TUI again.
