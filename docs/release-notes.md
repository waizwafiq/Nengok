# Release engineering notes: v0.1.0

Working log for the steps between "works on my machine" and `pip install nengok` succeeding for a stranger. The polished changelog lives in [CHANGELOG.md](../CHANGELOG.md); this file records what broke and how each break was fixed, so the next release does not rediscover the same problems.

## PyPI name claim

Checked on 2026-06-10: `https://pypi.org/pypi/nengok/json` returns 404, so the name is unclaimed and every badge and install instruction in the repo can keep saying `nengok`. The fallback `nengok-sdk` is also free, so no rename is needed.

PyPI has no reservation step short of an upload; the name is claimed by the first successful publish. To make that publish work without an API token:

1. On pypi.org, add a pending trusted publisher for project `nengok` pointing at the `waizwafiq/Nengok` repo, workflow `publish.yml`, environment `pypi`. The tag-triggered publish job then claims the name on the first `v*.*.*` push.
2. On test.pypi.org, add the same pending publisher with environment `testpypi`. The dry-run job that fires on every `main` push exercises the full build-and-upload path there, so the first real release is not the first run of the workflow.

Both steps are dashboard actions for the repo owner; nothing else in the repo changes.

## Wheel smoke install, 2026-06-10

Built with `python -m build` on Windows 11 (Python 3.12.13, Node 20). The hatch hook bundled the Vite dashboard into the wheel, so the install carries the UI without Node on the target machine. The wheel and sdist were then installed into clean venvs on two machines:

- Windows 11, Python 3.12.13, `python -m venv`
- WSL2 Ubuntu 24.04, Python 3.12.3, `python3 -m venv`

Commands exercised on both: `nengok --version`, `nengok init --help`, `nengok init --non-interactive --phoenix-url ... --project travel-planner-agent`, `nengok run` against a fresh `phoenix serve` (data dir pointed at a throwaway `PHOENIX_WORKING_DIR`), and `nengok dashboard --no-browser` probed via `GET /health` and `GET /`.

### Failures found, and what fixed them

1. Ubuntu venv creation failed with "ensurepip is not available". Stock Ubuntu 24.04 ships `python3` without the venv module. Fix: `apt install python3.12-venv`, then recreate the venv. Worth a line in the README install section if bug reports show up.
2. `nengok init` on a bare `pip install nengok` failed its Gemini probe with "google-genai is not installed", but the printed fix hint said to get a fresh API key. The probe swallowed the `OptionalDependencyError` install hint. Fixed in `nengok/init_wizard.py`: the probe now prints `pip install nengok[gemini]` for that case. The CLI itself works without the extra; `run` needs `[phoenix,gemini]`.
3. `pip install 'nengok[phoenix,gemini] @ file:///D:/...'` rejects paths containing spaces ("Expected end or semicolon"). Percent-encode the path in the file URL, or copy the wheel somewhere space-free first. pip behavior, not ours; recorded here because this repo's checkout path has spaces.
4. `nengok run` against a clean Phoenix (configured project never created) dumped a raw `httpx.HTTPStatusError` traceback. Fixed in `nengok/phoenix/client.py`: a 404 from the span read now raises `PhoenixProjectNotFoundError`, so the CLI prints `Error (phoenix-project-missing): ...` with the seed command, exit 1, no traceback. Transport failures get `PhoenixConnectionError` the same way.

### What passed without changes

`nengok --version` prints `nengok 0.1.0` on both platforms. `nengok init --non-interactive` passes all three probes (Phoenix, Gemini, file write) and writes `config.toml`. Against an existing but empty project, `nengok run` completes a cycle in about 3 seconds with zero clusters, zero Gemini tokens, and exit 0. The dashboard serves the bundled SPA at `/` and `GET /health` returns 200 with `phoenix_reachable`, `gemini_reachable`, and `db_writable` all true.
