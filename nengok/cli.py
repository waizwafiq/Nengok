"""
The `nengok` CLI entry point.

Sub-commands:

    nengok init       Configure a local Nengok install
    nengok run        Execute one full Observe -> Diagnose -> Fix -> Verify cycle
    nengok watch      Continuous heartbeat mode (single-process, polls on an interval)
    nengok dashboard  Launch the local FastAPI + Vite approval UI
    nengok review     Launch the Textual approval TUI over an SSH-friendly session
    nengok doctor     Run a read-only health check across the install
"""

from __future__ import annotations

import json as _json
import os
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from dotenv import load_dotenv

from nengok import __version__
from nengok.config import DEFAULT_CONFIG_PATH, NengokConfig
from nengok.diagnostics import DEFAULT_PROBES, Probe, ProbeResult, ProbeStatus
from nengok.errors import (
    AgentRunnerLoadError,
    BaselinePromptError,
    ConfigError,
    GoldenDatasetError,
    MissingApiKeyError,
    NengokError,
    OptionalDependencyError,
    PhoenixConnectionError,
    PhoenixProjectNotFoundError,
)
from nengok.utils.gemini import GeminiAuthError, GeminiCallError, GeminiQuotaError
from nengok.utils.logging import configure_logging, get_logger


def _abort(message: str) -> typer.Exit:
    """
    Print `message` to stderr and return a `typer.Exit(2)` for the caller to raise.

    Using `typer.Exit` directly (rather than a `ClickException` subclass)
    keeps the CLI's exit code stable across Click versions, some of which
    no longer honor `ClickException.exit_code` set on a subclass.
    """
    typer.echo(f"Error: {message}", err=True)
    return typer.Exit(code=2)


app = typer.Typer(
    name="nengok",
    help="Phoenix shows you what's wrong. Nengok fixes it.",
    no_args_is_help=True,
    add_completion=False,
)

config_app = typer.Typer(
    name="config",
    help="Inspect and seed Nengok configuration files.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(config_app, name="config")

db_app = typer.Typer(
    name="db",
    help="Inspect and manage the Nengok state schema.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(db_app, name="db")

reviewer_app = typer.Typer(
    name="reviewer",
    help="Manage the reviewer identity used on approvals.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(reviewer_app, name="reviewer")

logger = get_logger(__name__)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"nengok {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version and exit."),
    ] = None,
    verbose: Annotated[bool, typer.Option("-v", "--verbose", help="Enable debug logging.")] = False,
) -> None:
    load_dotenv(override=False)
    # Cloud Run sets K_SERVICE on every revision; emit Cloud-Logging-parseable
    # JSON (with a `severity` field) there. NENGOK_LOG_FORMAT (text|json|gcp)
    # overrides the auto-detected default. `run`/`watch` re-configure logging
    # afterwards from their own --log-format option, so only `dashboard`
    # (which never re-configures) inherits this on Cloud Run.
    default_fmt = "gcp" if os.environ.get("K_SERVICE") else "text"
    configure_logging(
        verbose=verbose,
        log_format=os.environ.get("NENGOK_LOG_FORMAT", default_fmt),
    )


@app.command()
def init(
    phoenix_url: Annotated[
        str | None, typer.Option("--phoenix-url", help="Base URL of your Phoenix instance.")
    ] = None,
    phoenix_api_key_flag: Annotated[
        str | None,
        typer.Option(
            "--phoenix-api-key",
            "--api-key",
            help="Phoenix API key (only needed for Cloud or auth-gated Phoenix).",
        ),
    ] = None,
    google_api_key_flag: Annotated[
        str | None,
        typer.Option("--google-api-key", help="Gemini API key. Falls back to GOOGLE_API_KEY."),
    ] = None,
    project: Annotated[
        str | None,
        typer.Option("--project", help="Phoenix project identifier to monitor."),
    ] = None,
    agent_runner: Annotated[
        str | None,
        typer.Option("--agent-runner", help="Dotted path 'module.path:ClassName' for the monitored agent."),
    ] = None,
    config_path: Annotated[
        Path, typer.Option("--config-path", help="Where to write the config file.")
    ] = DEFAULT_CONFIG_PATH,
    non_interactive: Annotated[
        bool,
        typer.Option(
            "--non-interactive",
            help="Skip prompts; all values must come from flags or env. Exits nonzero on any miss.",
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="Write the config even if the connectivity probes fail."),
    ] = False,
) -> None:
    """Interactive wizard that writes a working ~/.nengok/config.toml."""
    from nengok import init_wizard
    from nengok.cli_helpers import write_config_file

    phoenix_base_url, phoenix_api_key, google_api_key, project_name, runner_choice = _collect_init_values(
        phoenix_url=phoenix_url,
        phoenix_api_key_flag=phoenix_api_key_flag,
        google_api_key_flag=google_api_key_flag,
        project=project,
        agent_runner=agent_runner,
        non_interactive=non_interactive,
    )

    typer.echo("")
    typer.echo("Running connectivity probes...")
    results = init_wizard.run_probes(
        phoenix_base_url=phoenix_base_url,
        phoenix_api_key=phoenix_api_key,
        google_api_key=google_api_key,
        target_dir=config_path.parent,
    )
    typer.echo(init_wizard.format_probe_summary(results))

    if not init_wizard.all_passed(results) and not force:
        typer.echo("", err=True)
        typer.echo(
            "One or more probes failed. Fix the issue above or rerun with --force to write anyway.", err=True
        )
        raise typer.Exit(code=1)

    written = write_config_file(
        config_path=config_path,
        phoenix_base_url=phoenix_base_url,
        phoenix_api_key=phoenix_api_key,
        project_identifier=project_name,
        google_api_key=google_api_key,
        agent_runner=runner_choice,
    )
    typer.echo("")
    typer.echo(f"Wrote {written}.")
    if not os.environ.get("DATABASE_URL"):
        typer.echo(
            "Nengok is using SQLite at ~/.nengok/state.db. "
            "To use your own database, set DATABASE_URL "
            "(postgresql://... or mysql+pymysql://...) and re-run nengok init."
        )
    typer.echo(
        "Next: run `python -m sample_agent.seed --count 5` to seed traces, then `nengok run` to see your first cycle."
    )


def _collect_init_values(
    *,
    phoenix_url: str | None,
    phoenix_api_key_flag: str | None,
    google_api_key_flag: str | None,
    project: str | None,
    agent_runner: str | None,
    non_interactive: bool,
) -> tuple[str, str | None, str, str, str | None]:
    """
    Resolve the five required values from flags, env, and (optionally) prompts.

    Order of precedence per value: CLI flag wins, then env var, then the
    wizard prompt. `--non-interactive` skips the prompt step and exits 2
    if anything is still missing afterwards.
    """
    from nengok import init_wizard

    phoenix_base_url = phoenix_url or init_wizard.env_default("PHOENIX_BASE_URL")
    phoenix_api_key = phoenix_api_key_flag or init_wizard.env_default("PHOENIX_API_KEY")
    google_api_key = google_api_key_flag or init_wizard.env_default("GOOGLE_API_KEY")
    project_name = project or init_wizard.env_default("NENGOK_PROJECT")
    runner_choice = agent_runner

    if non_interactive:
        missing: list[str] = []
        if not phoenix_base_url:
            missing.append("--phoenix-url / PHOENIX_BASE_URL")
        if not google_api_key:
            missing.append("--google-api-key / GOOGLE_API_KEY")
        if not project_name:
            missing.append("--project / NENGOK_PROJECT")
        if missing:
            typer.echo("Error: --non-interactive requires these values:", err=True)
            for item in missing:
                typer.echo(f"  - {item}", err=True)
            raise typer.Exit(code=2)
        return (
            phoenix_base_url or "",
            phoenix_api_key,
            google_api_key or "",
            project_name or "",
            runner_choice,
        )

    if not phoenix_base_url:
        phoenix_base_url, prompted_api_key = init_wizard.prompt_phoenix_choice()
        if phoenix_api_key is None:
            phoenix_api_key = prompted_api_key

    if not google_api_key:
        google_api_key = init_wizard.prompt_google_api_key(
            probe=lambda key: init_wizard.probe_gemini(api_key=key),
        )

    if not project_name:
        project_name = init_wizard.prompt_project_name()

    if runner_choice is None:
        runner_choice = init_wizard.prompt_agent_runner()

    return phoenix_base_url, phoenix_api_key, google_api_key, project_name, runner_choice


@app.command()
def run(
    project: Annotated[
        str | None,
        typer.Option("--project", help="Override the configured Phoenix project."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Run the full pipeline but do not write artifacts or experiments."),
    ] = False,
    skip_preflight: Annotated[
        bool,
        typer.Option("--skip-preflight", help="Skip the MCP project existence check."),
    ] = False,
    log_format: Annotated[
        str,
        typer.Option("--log-format", help="Log output format: text (default) or json."),
    ] = "text",
) -> None:
    """Execute one full Observe -> Diagnose -> Fix -> Verify cycle."""
    from nengok.core.orchestrator import Orchestrator
    from nengok.phoenix.preflight import run_preflight

    configure_logging(json_format=log_format == "json")

    config = _load_config(project_identifier=project)
    if not skip_preflight:
        run_preflight(config, echo=lambda msg: typer.echo(msg, err=True))

    orchestrator = Orchestrator(config=config)
    try:
        result = orchestrator.run_once(dry_run=dry_run)
    except NengokError as exc:
        _report_external_error(exc)
        raise typer.Exit(code=1) from exc

    typer.echo(
        f"Cycle complete: {result.clusters_detected} clusters detected, "
        f"{result.fixes_proposed} fixes proposed, {result.escalations} escalations."
    )
    if result.fixes_proposed > 0:
        typer.echo("Run `nengok dashboard` to review and approve.")


@app.command()
def watch(
    interval_seconds: Annotated[
        int,
        typer.Option("--interval", help="Seconds between cycles. Default: 300 (5 minutes)."),
    ] = 300,
    project: Annotated[
        str | None, typer.Option("--project", help="Override the configured Phoenix project.")
    ] = None,
    log_format: Annotated[
        str,
        typer.Option("--log-format", help="Log output format: json (default) or text."),
    ] = "json",
) -> None:
    """
    Continuously run cycles on a fixed interval.

    A circuit breaker pauses the loop after the configured number of
    consecutive failures in the same stage. SIGTERM and SIGINT shut
    the process down cleanly, leaving the SQLite state consistent.
    """
    import signal

    from nengok.core.circuit_breaker import CircuitBreaker
    from nengok.core.incidents import write_incident
    from nengok.core.orchestrator import Orchestrator

    configure_logging(json_format=log_format == "json")

    config = _load_config(project_identifier=project)
    orchestrator = Orchestrator(config=config)
    breaker = CircuitBreaker(
        threshold=config.circuit_breaker_consecutive_failures,
        backoff_seconds=config.circuit_breaker_backoff_seconds,
    )

    stop_requested = False

    def _request_stop(signum: int, frame: Any) -> None:
        del signum, frame
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGINT, _request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _request_stop)

    typer.echo(f"Watching project '{config.project_identifier}' every {interval_seconds}s. Ctrl-C to stop.")

    while not stop_requested:
        try:
            orchestrator.run_once()
            stage = orchestrator.current_stage or "cycle"
            breaker.record_success(stage)
        except NengokError as exc:
            stage = orchestrator.current_stage or "cycle"
            opened = breaker.record_failure(stage, exc)
            _report_external_error(exc, prefix=f"Cycle skipped in '{stage}'")
            if opened:
                _open_breaker_pause(breaker=breaker, config=config, write_incident=write_incident)
        except Exception as exc:
            stage = orchestrator.current_stage or "cycle"
            opened = breaker.record_failure(stage, exc)
            typer.echo(f"Cycle failed in '{stage}': {exc}", err=True)
            if opened:
                _open_breaker_pause(breaker=breaker, config=config, write_incident=write_incident)

        if stop_requested:
            break
        _interruptible_sleep(interval_seconds, lambda: stop_requested)

    typer.echo("\nStopped.")


def _interruptible_sleep(total_seconds: float, should_stop: Any) -> None:
    """Sleep in small slices so SIGTERM/SIGINT exit fast."""
    import time

    slept = 0.0
    slice_seconds = 0.5
    while slept < total_seconds:
        if should_stop():
            return
        chunk = min(slice_seconds, total_seconds - slept)
        time.sleep(chunk)
        slept += chunk


def _open_breaker_pause(*, breaker: Any, config: NengokConfig, write_incident: Any) -> None:
    """Pause for the breaker's back-off and write a circuit-breaker incident."""
    import time

    stage = breaker.open_stage
    backoff = breaker.backoff_seconds
    body_lines = [
        f"- failing_stage: `{stage}`",
        f"- consecutive_failures: {breaker.threshold}",
        f"- backoff_seconds: {backoff}",
        "",
        "Recent tracebacks (newest last):",
        "",
    ]
    for failure in breaker.recent_failures():
        body_lines.append(f"### {failure.recorded_at.isoformat()} :: {failure.error_class}")
        body_lines.append("")
        body_lines.append("```")
        body_lines.append(failure.traceback.strip())
        body_lines.append("```")
        body_lines.append("")
    write_incident(
        artifacts_dir=config.artifacts_dir,
        filename="circuit-breaker.md",
        title=f"Circuit breaker tripped in stage '{stage}'",
        body="\n".join(body_lines),
    )
    minutes = backoff / 60
    typer.echo(
        f"Nengok watch paused for {minutes:.0f} min after "
        f"{breaker.threshold} consecutive {stage} failures. "
        "See artifacts/incidents/<iso>/circuit-breaker.md to investigate.",
        err=True,
    )
    time.sleep(backoff)
    breaker.close()


@app.command()
def dashboard(
    listen: Annotated[
        str | None,
        typer.Option(
            "--listen",
            help="Dashboard bind address. Defaults to dashboard_host in config (127.0.0.1).",
        ),
    ] = None,
    port: Annotated[int, typer.Option("--port", help="Dashboard port.")] = 8765,
    no_browser: Annotated[
        bool, typer.Option("--no-browser", help="Do not open a browser window automatically.")
    ] = False,
) -> None:
    """Launch the local FastAPI dashboard server."""
    import uvicorn

    from nengok.server.main import create_app

    config = _load_config()
    bind_host = listen or config.dashboard_host
    _enforce_dashboard_safety(config=config, bind_host=bind_host)
    fastapi_app = create_app(config=config)

    if not no_browser:
        import threading
        import webbrowser

        url = f"http://{bind_host}:{port}"
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    # Route uvicorn's own access/error logs through the root logger so they
    # share Nengok's formatter (including the gcp `severity` formatter on
    # Cloud Run) and pass through the redaction filter.
    uvicorn_log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "loggers": {
            "uvicorn": {"handlers": [], "level": "INFO", "propagate": True},
            "uvicorn.error": {"handlers": [], "level": "INFO", "propagate": True},
            "uvicorn.access": {"handlers": [], "level": "INFO", "propagate": True},
        },
    }
    uvicorn.run(
        fastapi_app,
        host=bind_host,
        port=port,
        log_level="info",
        log_config=uvicorn_log_config,
    )


_LOCAL_BIND_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _enforce_dashboard_safety(*, config: NengokConfig, bind_host: str) -> None:
    """
    Print the LAN-exposure warning and refuse to boot in unsafe production setups.

    Two checks. First, any bind address outside the localhost set gets a
    one-shot stderr warning so an operator who typed `--listen 0.0.0.0`
    is reminded that RCA documents are now reachable to the network.
    Second, `NENGOK_PRODUCTION=true` is the Cloud Run safety net: the
    dashboard refuses to start unless both an auth token is configured
    and the bind is not localhost-only, on the assumption that prod
    deployments need external reach and must also be locked.
    """
    is_local = bind_host in _LOCAL_BIND_HOSTS
    if not is_local:
        typer.echo(
            f"Nengok dashboard is binding to {bind_host}. "
            "Anyone on this network can read failure RCA documents. "
            "Set dashboard_auth_token in ~/.nengok/config.toml to require an Authorization header.",
            err=True,
        )

    if not _parse_bool_env(os.environ.get("NENGOK_PRODUCTION")):
        return

    problems: list[str] = []
    if not config.dashboard_auth_token:
        problems.append(
            "dashboard_auth_token is unset; set it in ~/.nengok/config.toml or "
            "via NENGOK_DASHBOARD_AUTH_TOKEN."
        )
    if is_local:
        problems.append(
            f"bind address '{bind_host}' is localhost-only; pass --listen 0.0.0.0 or set "
            "NENGOK_DASHBOARD_HOST to expose the service in production."
        )
    if problems:
        typer.echo(
            "Refusing to start: NENGOK_PRODUCTION=true requires a hardened dashboard.",
            err=True,
        )
        for item in problems:
            typer.echo(f"  - {item}", err=True)
        raise typer.Exit(code=2)


def _parse_bool_env(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


@app.command()
def review(
    host: Annotated[
        str | None,
        typer.Option(
            "--host",
            help="Hostname of the Nengok FastAPI server. Defaults to dashboard_host in config.",
        ),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option("--port", help="Port the Nengok FastAPI server is listening on."),
    ] = None,
    auth_token: Annotated[
        str | None,
        typer.Option(
            "--auth-token",
            help="Bearer token sent on every API call. Falls back to dashboard_auth_token.",
        ),
    ] = None,
) -> None:
    """Launch the Textual approval TUI against a local or remote Nengok server."""
    try:
        from nengok.tui.api_client import TuiApiClient
        from nengok.tui.app import NengokReviewApp
    except ModuleNotFoundError as exc:
        raise OptionalDependencyError(
            "The `nengok review` TUI requires the optional `tui` extra.",
            install_hint='pip install "nengok[tui]"',
        ) from exc

    config = _load_config()
    bind_host = host or config.dashboard_host or "127.0.0.1"
    bind_port = port or config.dashboard_port or 8765
    token = auth_token or config.dashboard_auth_token
    base_url = f"http://{bind_host}:{bind_port}"

    client = TuiApiClient(base_url=base_url, auth_token=token)
    try:
        _probe_review_server(client=client, base_url=base_url)
    except NengokError as exc:
        _report_external_error(exc)
        raise typer.Exit(code=1) from exc

    NengokReviewApp(api_client=client).run()


def _probe_review_server(*, client: Any, base_url: str) -> None:
    """Hit `/health` once before launching the App so a bad URL fails loud."""
    import asyncio

    import httpx

    try:
        asyncio.run(client.ping())
    except httpx.HTTPError as exc:
        raise PhoenixConnectionError(
            f"Nengok review could not reach the FastAPI server at {base_url}: {exc}. "
            "Start it with `nengok dashboard --no-browser`, or pass --host/--port to target a remote instance."
        ) from exc


@app.command()
def doctor(
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Treat warnings as failures (exit 1 on any warn)."),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON instead of the text report."),
    ] = False,
) -> None:
    """Run a read-only health check across the install."""
    try:
        config = NengokConfig.load()
    except ConfigError as exc:
        if json_output:
            failure = ProbeResult(
                name="config",
                status=ProbeStatus.FAIL,
                detail=str(exc),
                fix_hint="Run `nengok init` to write a working ~/.nengok/config.toml.",
            )
            _print_doctor_json(version=__version__, results=[failure])
        else:
            typer.echo(f"Nengok v{__version__} health check")
            typer.echo(f"  [fail] config: {exc}")
            typer.echo("    Fix: run `nengok init` to write a working ~/.nengok/config.toml.")
        raise typer.Exit(code=1) from exc

    results = _run_probes(config=config, probes=DEFAULT_PROBES)
    scope = _describe_connection_scope(config=config, privilege_result=_find_result(results, "db-privileges"))

    if json_output:
        _print_doctor_json(version=__version__, results=results, connection_scope=scope)
    else:
        _print_doctor_text(version=__version__, results=results, connection_scope=scope)

    exit_code = _doctor_exit_code(results=results, strict=strict)
    if exit_code != 0:
        raise typer.Exit(code=exit_code)


def _run_probes(*, config: NengokConfig, probes: tuple[Probe, ...]) -> list[ProbeResult]:
    results: list[ProbeResult] = []
    for probe in probes:
        try:
            results.append(probe(config))
        except Exception as exc:
            results.append(
                ProbeResult(
                    name=getattr(probe, "__name__", "probe"),
                    status=ProbeStatus.FAIL,
                    detail=f"probe raised {exc.__class__.__name__}: {exc}",
                    fix_hint="Re-run `nengok doctor -v` for the full traceback.",
                )
            )
    return results


def _print_doctor_text(
    *,
    version: str,
    results: list[ProbeResult],
    connection_scope: dict[str, str] | None = None,
) -> None:
    typer.echo(f"Nengok v{version} health check")
    for result in results:
        marker = result.status.value
        typer.echo(f"  [{marker}] {result.name}: {result.detail}")
        if result.status != ProbeStatus.OK and result.fix_hint:
            typer.echo(f"    Fix: {result.fix_hint}")
    if connection_scope:
        typer.echo("Connection scope:")
        for key, value in connection_scope.items():
            typer.echo(f"  {key}: {value}")


def _print_doctor_json(
    *,
    version: str,
    results: list[ProbeResult],
    connection_scope: dict[str, str] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "nengok_version": version,
        "results": [r.to_dict() for r in results],
    }
    if connection_scope:
        payload["connection_scope"] = connection_scope
    typer.echo(_json.dumps(payload, indent=2))


def _find_result(results: list[ProbeResult], name: str) -> ProbeResult | None:
    for result in results:
        if result.name == name:
            return result
    return None


def _describe_connection_scope(
    *,
    config: NengokConfig,
    privilege_result: ProbeResult | None,
) -> dict[str, str]:
    """
    Return one-line-per-attribute summary of the active database connection.

    Sensitive fields (`user`, `host`) are masked the same way as
    `nengok config show`. SQLite connections collapse the host/port/user
    columns to `<local file>` because the dialect has no network surface.
    """
    from sqlalchemy.engine import make_url

    from nengok.cli_helpers import mask_secret

    url_str = config.database_url
    if not url_str:
        return {"dialect": "<unset>", "scope": "no DATABASE_URL resolved"}

    url = make_url(url_str)
    driver = url.drivername
    privilege_detail = privilege_result.detail if privilege_result else "<not run>"

    if driver.startswith("sqlite"):
        return {
            "dialect": driver,
            "host": "<local file>",
            "port": "<n/a>",
            "user": "<n/a>",
            "database": str(url.database) if url.database else "<memory>",
            "tls": "n/a (local file)",
            "privilege": privilege_detail,
        }

    host_loopback = (url.host or "").lower() in {"localhost", "127.0.0.1", "::1"}
    host_display = url.host or "<unset>" if host_loopback else mask_secret(url.host)
    user_display = mask_secret(url.username) if url.username else "<unset>"
    return {
        "dialect": driver,
        "host": host_display,
        "port": str(url.port) if url.port else "<default>",
        "user": user_display,
        "database": url.database or "<unset>",
        "tls": _tls_label(driver, host_loopback, bool(config.database_allow_plaintext)),
        "privilege": privilege_detail,
    }


def _tls_label(driver: str, host_loopback: bool, allow_plaintext: bool) -> str:
    if host_loopback:
        return "loopback (plaintext acceptable)"
    if allow_plaintext:
        return "plaintext (database_allow_plaintext=true)"
    if driver.startswith("postgresql"):
        return "require (sslmode=require)"
    if driver.startswith("mysql"):
        return "enabled (ssl=true)"
    return "<unknown dialect>"


def _doctor_exit_code(*, results: list[ProbeResult], strict: bool) -> int:
    if any(r.failed for r in results):
        return 1
    if strict and any(r.warned for r in results):
        return 1
    return 0


def _report_external_error(exc: NengokError, *, prefix: str = "Error") -> None:
    """
    Print a tailored, one-line-plus-hint message for `exc` to stderr.

    The CLI catches the typed base class and dispatches here so each
    failure class gets a specific next step. The exception's own
    `__str__` already carries the actionable detail (env var to set,
    URL to visit) per `nengok/errors.py`; this layer adds a short
    classifier prefix and prints any extra structured fields.
    """
    label = _error_label(exc)
    typer.echo(f"{prefix} ({label}): {exc}", err=True)

    if isinstance(exc, OptionalDependencyError):
        typer.echo(f"  Fix: {exc.install_hint}", err=True)
    elif isinstance(exc, GeminiQuotaError):
        if exc.retry_after_seconds is not None:
            typer.echo(f"  Retry after: {exc.retry_after_seconds:.0f}s", err=True)
        if exc.quota_id is not None:
            typer.echo(f"  Quota id: {exc.quota_id}", err=True)


def _error_label(exc: NengokError) -> str:
    """Short, kebab-case classifier for the typed exception class."""
    mapping: dict[type[NengokError], str] = {
        MissingApiKeyError: "missing-api-key",
        OptionalDependencyError: "missing-dependency",
        BaselinePromptError: "missing-baseline-prompt",
        GoldenDatasetError: "golden-dataset-missing",
        AgentRunnerLoadError: "agent-runner-not-registered",
        PhoenixConnectionError: "phoenix-unreachable",
        PhoenixProjectNotFoundError: "phoenix-project-missing",
        GeminiAuthError: "gemini-auth",
        GeminiQuotaError: "gemini-quota",
        GeminiCallError: "gemini-call",
    }
    for cls, label in mapping.items():
        if isinstance(exc, cls):
            return label
    return "nengok-error"


_STARTUP_BANNER_LOGGED = False


def _load_config(*, config_path: Path | None = None, **overrides: Any) -> NengokConfig:
    try:
        cleaned = {k: v for k, v in overrides.items() if v is not None}
        if config_path is not None:
            cleaned["config_path"] = config_path
        config = NengokConfig.load(**cleaned)
    except ConfigError as exc:
        raise _abort(str(exc)) from exc
    except ValueError as exc:
        raise _abort(str(exc)) from exc

    _log_startup_banner(config, config_path=config_path)
    return config


def _log_startup_banner(config: NengokConfig, *, config_path: Path | None = None) -> None:
    """
    Emit one INFO line per process so missing redaction is visible in operations.

    Idempotent across the lifetime of the process: `nengok watch` calls
    `_load_config()` again on a config reload, but operators only need
    the banner once. Cite the version, the config path actually read,
    whether the redactor will run, and the Phoenix URL so a log shipper
    has the full operational fingerprint of this invocation in one line.
    """
    global _STARTUP_BANNER_LOGGED
    if _STARTUP_BANNER_LOGGED:
        return
    redaction_state = "enabled" if config.redaction_enabled else "disabled"
    chosen_path = config_path or DEFAULT_CONFIG_PATH
    resolved = chosen_path if chosen_path.exists() else Path("<env-only>")
    logger.info(
        "nengok v%s starting (config: %s, redaction: %s, phoenix: %s)",
        __version__,
        resolved,
        redaction_state,
        config.phoenix_base_url,
    )
    _STARTUP_BANNER_LOGGED = True


def _reset_startup_banner_for_tests() -> None:
    """Allow the suite to re-arm the banner between CliRunner invocations."""
    global _STARTUP_BANNER_LOGGED
    _STARTUP_BANNER_LOGGED = False


@config_app.command("init")
def config_init(
    template: Annotated[
        str,
        typer.Option(
            "--template",
            help="Template to write: 'local', 'cloud', or 'qa-agent'.",
        ),
    ] = "local",
    config_path: Annotated[
        Path,
        typer.Option("--config-path", help="Where to write the config file."),
    ] = DEFAULT_CONFIG_PATH,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite an existing config file."),
    ] = False,
) -> None:
    """
    Write a documented config template to disk without prompting.

    For users who do not want the interactive `nengok init` wizard.
    The output is the same template `nengok init` seeds from, with
    every available field commented in plain English.
    """
    from nengok import templates as template_pkg
    from nengok.cli_helpers import render_template

    if template not in template_pkg.list_templates():
        available = ", ".join(template_pkg.list_templates())
        raise _abort(f"Unknown template '{template}'. Available templates: {available}.")

    if config_path.exists() and not force:
        raise _abort(
            f"{config_path} already exists. Pass --force to overwrite, " "or pick a different --config-path."
        )

    config_path.parent.mkdir(parents=True, exist_ok=True)
    body = render_template(template)
    config_path.write_text(body, encoding="utf-8")
    typer.echo(f"Wrote {config_path} from the '{template}' template.")
    typer.echo(
        "Open it to fill in GOOGLE_API_KEY (or set the env var), then run "
        "`nengok doctor` to verify the install."
    )


@config_app.command("show")
def config_show(
    config_path: Annotated[
        Path,
        typer.Option("--config-path", help="Path to read instead of the default."),
    ] = DEFAULT_CONFIG_PATH,
) -> None:
    """
    Print the loaded config with every secret masked.

    Lets users debug a misbehaving install (wrong Phoenix URL, stale
    project name, etc.) without dumping raw keys into a paste buffer.
    `google_api_key`, `phoenix_api_key`, and `dashboard_auth_token`
    render as `AIza****1234`; an unset value renders as `<unset>`.
    """
    from nengok.cli_helpers import format_config_for_display

    config = _load_config(config_path=config_path)

    typer.echo(f"# Loaded from {config_path if config_path.exists() else '<env-only>'}")
    typer.echo(format_config_for_display(config))


@app.command("export")
def export(
    since: Annotated[
        str | None,
        typer.Option("--since", help="Lower date bound (YYYY-MM-DD, UTC). Inclusive."),
    ] = None,
    until: Annotated[
        str | None,
        typer.Option("--until", help="Upper date bound (YYYY-MM-DD, UTC). Inclusive."),
    ] = None,
    output_format: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format: 'json' (default) or 'csv'."),
    ] = "json",
    output_path: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Write to this file instead of stdout. Parent directories are created if missing.",
        ),
    ] = None,
) -> None:
    """
    Dump clusters, approvals, experiments, cycles, and artifact pointers as an audit bundle.

    JSON output matches the schema in `docs/audit-export.md` and is the
    seed for the v1.0 EU AI Act audit bundle. CSV output emits two
    sections (`# clusters` then `# approvals`) so a reviewer can split
    the stream and import each block into a spreadsheet.
    """
    from nengok.state.export import (
        ExportDateError,
        build_bundle,
        parse_date_argument,
        serialize_csv,
        serialize_json,
    )
    from nengok.state.store import StateStore

    fmt = output_format.lower()
    if fmt not in {"json", "csv"}:
        raise _abort(f"Unknown --format '{output_format}'. Pick 'json' or 'csv'.")

    config = _load_config()
    if not config.state_db_path.exists():
        raise _abort(
            f"No state database at {config.state_db_path}. "
            "Run `nengok db migrate` (or `nengok run`) to create it."
        )

    try:
        since_dt = parse_date_argument(since, kind="since")
        until_dt = parse_date_argument(until, kind="until")
    except ExportDateError as exc:
        raise _abort(str(exc)) from exc

    store = StateStore(config.state_db_path, schema=config.database_schema)
    try:
        bundle = build_bundle(
            store=store,
            artifacts_dir=config.artifacts_dir,
            since=since_dt,
            until=until_dt,
        )
    except ExportDateError as exc:
        raise _abort(str(exc)) from exc

    rendered = serialize_json(bundle) if fmt == "json" else serialize_csv(bundle)

    if output_path is None:
        typer.echo(rendered)
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    typer.echo(
        f"Wrote {fmt} export to {output_path} "
        f"(clusters={len(bundle.clusters)}, approvals={len(bundle.approvals)}, "
        f"experiments={len(bundle.experiments)}, cycles={len(bundle.cycles)}, "
        f"artifacts={len(bundle.artifacts)}).",
        err=True,
    )


@db_app.command("migrate")
def db_migrate() -> None:
    """
    Apply pending Alembic revisions against the configured state database.

    A no-op when the database is already at head. The runner is the
    same `alembic upgrade head` that `StateStore.__init__` invokes on
    first connect, so running it from the CLI matches in-process
    behaviour exactly.
    """
    from alembic import command
    from alembic.util import CommandError

    from nengok.state.alembic_runner import build_config, current_revision
    from nengok.state.connection import ConnectionFactory

    config = _load_config()
    factory = ConnectionFactory(config)
    engine = factory.engine()
    before = current_revision(engine)
    try:
        command.upgrade(build_config(engine), "head")
    except CommandError as exc:
        factory.dispose()
        raise _abort(str(exc)) from exc

    after = current_revision(engine)
    factory.dispose()

    if before == after:
        typer.echo("No pending migrations. Database is up to date.")
        return
    typer.echo(f"Upgraded to revision {after}.")


@db_app.command("status")
def db_status() -> None:
    """
    Print every Alembic revision with its position relative to the live database.

    Use this to confirm a freshly cloned environment matches a deployed
    one before promoting a change.
    """
    from nengok.state.alembic_runner import current_revision, script_directory
    from nengok.state.connection import ConnectionFactory

    config = _load_config()
    factory = ConnectionFactory(config)
    engine = factory.engine()
    try:
        live = current_revision(engine)
        scripts = script_directory(engine)
        revisions = list(scripts.walk_revisions(base="base", head="heads"))
    finally:
        factory.dispose()

    revisions.reverse()
    if not revisions:
        typer.echo("No Alembic revisions packaged with this install.")
        raise typer.Exit(code=1)

    typer.echo(f"{'revision':<32}  state")
    found_live = live is None
    for script in revisions:
        if not found_live and script.revision == live:
            marker = "current"
            found_live = True
        elif found_live:
            marker = "pending"
        else:
            marker = "applied"
        typer.echo(f"{script.revision:<32}  {marker}")


@db_app.command("check")
def db_check() -> None:
    """
    Verify the live database is stamped at the latest packaged revision.

    Exits 0 when the live revision matches `head`, 1 otherwise. Replaces
    the old per-file checksum probe: Alembic revisions are content-hashed
    by their own revision id and refusing to run an unknown id is the
    portable equivalent of the legacy drift check.
    """
    from nengok.state.alembic_runner import current_revision, script_directory
    from nengok.state.connection import ConnectionFactory

    config = _load_config()
    factory = ConnectionFactory(config)
    engine = factory.engine()
    try:
        live = current_revision(engine)
        scripts = script_directory(engine)
        head = scripts.get_current_head()
    finally:
        factory.dispose()

    if live == head:
        typer.echo(f"Database is at revision {head}.")
        return
    typer.echo(
        f"Database revision {live} does not match the packaged head {head}. " "Run `nengok db migrate`.",
        err=True,
    )
    raise typer.Exit(code=1)


@reviewer_app.command("set")
def reviewer_set(
    name: Annotated[str, typer.Argument(help="Reviewer display name. Recorded against every approval.")],
    email: Annotated[
        str | None,
        typer.Option("--email", help="Optional email. Stored as 'Name <email>' for the audit log."),
    ] = None,
) -> None:
    """Persist the reviewer identity to `~/.nengok/reviewer.txt`."""
    from nengok.reviewer import format_identity, write_identity

    try:
        identity = format_identity(name, email)
    except ValueError as exc:
        raise _abort(str(exc)) from exc

    target = write_identity(identity)
    typer.echo(f"Wrote reviewer identity to {target}.")
    typer.echo(f"Approvals will record `{identity}` until you change it.")


@reviewer_app.command("show")
def reviewer_show() -> None:
    """Print the resolved reviewer identity and where it came from."""
    from nengok.reviewer import REVIEWER_ENV_VAR, REVIEWER_FILE_PATH, resolve_reviewer

    identity, source = resolve_reviewer(None)
    typer.echo(f"reviewer: {identity}")
    typer.echo(f"source:   {source}")
    if source == "fallback":
        typer.echo("")
        typer.echo('No identity configured. Run `nengok reviewer set "Your Name" --email you@example.com`')
        typer.echo(f"or export {REVIEWER_ENV_VAR}=... to label approvals.")
    elif source == "file":
        typer.echo(f"file:     {REVIEWER_FILE_PATH}")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(app())
