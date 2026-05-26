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

import click
import typer
from dotenv import load_dotenv

from nengok import __version__
from nengok.config import DEFAULT_CONFIG_PATH, NengokConfig
from nengok.errors import ConfigError
from nengok.utils.gemini import GeminiCallError
from nengok.utils.logging import configure_logging, get_logger


class NengokCLIError(click.ClickException):
    """Click exception that exits 2 and prints just the message, no traceback."""

    exit_code = 2

    def format_message(self) -> str:
        return self.message


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
    except ConfigError as exc:
        raise NengokCLIError(str(exc)) from exc
    except ValueError as exc:
        raise NengokCLIError(str(exc)) from exc


if __name__ == "__main__":  # pragma: no cover
    sys.exit(app())
