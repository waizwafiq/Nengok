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
) -> None:
    """Execute one full Observe -> Diagnose -> Fix -> Verify cycle."""
    from nengok.core.orchestrator import Orchestrator

    config = _load_config(project_identifier=project)
    orchestrator = Orchestrator(config=config)
    result = orchestrator.run_once(dry_run=dry_run)

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

    This is the simplest possible heartbeat: a single process that
    sleeps between cycles. Production deployments should use an
    event-driven scheduler — see Section 9b of the proposal.
    """
    import time

    from nengok.core.orchestrator import Orchestrator

    config = _load_config(project_identifier=project)
    orchestrator = Orchestrator(config=config)

    typer.echo(f"Watching project '{config.project_identifier}' every {interval_seconds}s. Ctrl-C to stop.")
    try:
        while True:
            orchestrator.run_once()
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        typer.echo("\nStopped.")


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
