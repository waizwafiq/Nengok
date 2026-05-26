"""
The `nengok` CLI entry point.

Sub-commands:

    nengok init       Configure a local Nengok install
    nengok run        Execute one full Observe -> Diagnose -> Fix -> Verify cycle
    nengok watch      Continuous heartbeat mode (single-process, polls on an interval)
    nengok dashboard  Launch the local FastAPI + Vite approval UI
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from dotenv import load_dotenv

from nengok import __version__
from nengok.config import DEFAULT_CONFIG_PATH, NengokConfig
from nengok.utils.gemini import GeminiCallError
from nengok.utils.logging import configure_logging, get_logger

app = typer.Typer(
    name="nengok",
    help="Phoenix shows you what's wrong. Nengok fixes it.",
    no_args_is_help=True,
    add_completion=False,
)

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
    configure_logging(verbose=verbose)


@app.command()
def init(
    phoenix_url: Annotated[str, typer.Option("--phoenix-url", help="Base URL of your Phoenix instance.")],
    api_key: Annotated[
        str | None,
        typer.Option(
            "--api-key", help="Phoenix API key. If omitted, falls back to PHOENIX_API_KEY at runtime."
        ),
    ] = None,
    project: Annotated[
        str,
        typer.Option("--project", help="Phoenix project identifier to monitor."),
    ] = "default",
    config_path: Annotated[
        Path, typer.Option("--config-path", help="Where to write the config file.")
    ] = DEFAULT_CONFIG_PATH,
) -> None:
    """Write a local Nengok config file."""
    from nengok.cli_helpers import write_config_file

    written = write_config_file(
        config_path=config_path,
        phoenix_base_url=phoenix_url,
        phoenix_api_key=api_key,
        project_identifier=project,
    )
    typer.echo(f"Wrote {written}.")
    typer.echo("Next: nengok run")


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
) -> None:
    """Execute one full Observe -> Diagnose -> Fix -> Verify cycle."""
    from nengok.core.orchestrator import Orchestrator
    from nengok.phoenix.preflight import run_preflight

    config = _load_config(project_identifier=project)
    if not skip_preflight:
        run_preflight(config, echo=lambda msg: typer.echo(msg, err=True))

    orchestrator = Orchestrator(config=config)
    try:
        result = orchestrator.run_once(dry_run=dry_run)
    except GeminiCallError as exc:
        typer.echo(f"Error: {exc}", err=True)
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
        except GeminiCallError as exc:
            stage = orchestrator.current_stage or "cycle"
            opened = breaker.record_failure(stage, exc)
            typer.echo(f"Cycle skipped: {exc}", err=True)
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
    host: Annotated[str, typer.Option("--host", help="Dashboard bind address.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Dashboard port.")] = 8765,
    no_browser: Annotated[
        bool, typer.Option("--no-browser", help="Do not open a browser window automatically.")
    ] = False,
) -> None:
    """Launch the local FastAPI dashboard server."""
    import uvicorn

    from nengok.server.main import create_app

    config = _load_config()
    fastapi_app = create_app(config=config)

    if not no_browser:
        import threading
        import webbrowser

        url = f"http://{host}:{port}"
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    uvicorn.run(fastapi_app, host=host, port=port, log_level="info")


def _load_config(**overrides: Any) -> NengokConfig:
    try:
        cleaned = {k: v for k, v in overrides.items() if v is not None}
        return NengokConfig.load(**cleaned)
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


if __name__ == "__main__":  # pragma: no cover
    sys.exit(app())
