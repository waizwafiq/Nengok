"""
Interactive wizard pieces for `nengok init`.

The CLI command in `nengok/cli.py` is thin glue. The prompts and the
connectivity probes live here so they can be unit-tested with a fake
HTTP layer and a fake Gemini, and so the same probe set can be reused
by `nengok doctor` later.
"""

from __future__ import annotations

import os
import socket
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import click

DEFAULT_LOCAL_PHOENIX_URL = "http://localhost:6006"
PHOENIX_CLOUD_BASE_URL = "https://app.phoenix.arize.com"
DEFAULT_PROJECT_NAME = "travel-planner-agent"
DEFAULT_BUNDLED_AGENT_RUNNER = "nengok.runners.sample_agent_runner:SampleAgentRunner"


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of a single readiness probe."""

    name: str
    ok: bool
    detail: str
    fix_hint: str | None = None


def detect_local_phoenix(*, timeout_seconds: float = 2.0) -> bool:
    """
    Return True if a process is listening on the local Phoenix port.

    A TCP connect attempt is cheaper than an HTTP request and avoids
    pulling Phoenix into the import graph just for autodetection.
    """
    host, port = "localhost", 6006
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except OSError:
        return False


def prompt_phoenix_choice(
    *,
    detect: Callable[[], bool] = detect_local_phoenix,
    echo: Callable[[str], None] = click.echo,
    ask: Callable[..., str] = click.prompt,
) -> tuple[str, str | None]:
    """
    Ask where Phoenix lives and return `(base_url, api_key)`.

    Local detection picks option 3 as the default so the common path
    (developer running `phoenix serve`) is a single Enter keystroke.
    """
    local_running = detect()
    default_choice = "3" if local_running else "1"

    echo("Where is your Phoenix?")
    echo("  (1) Phoenix Cloud at app.phoenix.arize.com")
    echo("  (2) Self-hosted Phoenix")
    if local_running:
        echo(f"  (3) Local `phoenix serve` (detected on {DEFAULT_LOCAL_PHOENIX_URL})")
    else:
        echo("  (3) Local `phoenix serve` (not detected, will assume http://localhost:6006)")

    choice = ask("Choice", default=default_choice, show_default=True).strip()

    if choice == "1":
        cloud_key = ask("Phoenix Cloud API key", hide_input=True)
        return PHOENIX_CLOUD_BASE_URL, cloud_key
    if choice == "2":
        base_url = ask("Self-hosted Phoenix base URL").strip()
        self_hosted_key_raw = ask(
            "Phoenix API key (leave blank if your Phoenix has no auth)", default="", show_default=False
        )
        self_hosted_key: str | None = self_hosted_key_raw.strip() or None
        return base_url, self_hosted_key
    return DEFAULT_LOCAL_PHOENIX_URL, None


def looks_like_google_api_key(value: str) -> bool:
    """Cheap shape check so an obvious typo is caught before a network call."""
    return value.startswith("AIza") and len(value) >= 30


def prompt_google_api_key(
    *,
    probe: Callable[[str], ProbeResult],
    max_attempts: int = 3,
    ask: Callable[..., str] = click.prompt,
    echo: Callable[[str], None] = click.echo,
) -> str:
    """
    Prompt for `GOOGLE_API_KEY`, validating shape and then live-pinging Gemini.

    `probe` runs a one-token Gemini call so a wrong key is caught
    before the wizard writes anything to disk. Up to `max_attempts`
    tries before the wizard raises `click.Abort`.
    """
    for attempt in range(1, max_attempts + 1):
        candidate = ask("GOOGLE_API_KEY", hide_input=True).strip()
        if not looks_like_google_api_key(candidate):
            echo(
                f"  That value doesn't look like a Gemini key (expected 'AIza...'). Attempt {attempt}/{max_attempts}."
            )
            continue
        result = probe(candidate)
        if result.ok:
            return candidate
        echo(f"  Gemini rejected that key: {result.detail}. Attempt {attempt}/{max_attempts}.")
    raise click.Abort()


def prompt_project_name(
    *,
    ask: Callable[..., str] = click.prompt,
    default: str = DEFAULT_PROJECT_NAME,
) -> str:
    """Ask for the Phoenix project name, defaulting to the bundled sample."""
    return ask("Phoenix project name", default=default, show_default=True).strip() or default


def prompt_agent_runner(
    *,
    ask: Callable[..., str] = click.prompt,
    echo: Callable[[str], None] = click.echo,
) -> str | None:
    """
    Ask which agent runner to wire up.

    Returns `None` for the bundled sample (so `agent_runner` stays out
    of the on-disk config) or the dotted-path string the user pasted.
    """
    echo("Monitored-agent runner")
    echo("  (1) Bundled sample agent (travel-planner)")
    echo("  (2) Custom dotted path")
    choice = ask("Choice", default="1", show_default=True).strip()
    if choice == "1":
        return None
    return ask("agent_runner (module.path:ClassName)").strip()


def probe_phoenix_projects(
    *,
    base_url: str,
    api_key: str | None,
    timeout_seconds: float = 5.0,
    opener: Callable[[urllib.request.Request, float], Any] | None = None,
) -> ProbeResult:
    """
    Hit `GET /v1/projects` to confirm Phoenix is reachable and authorized.

    `opener` is injectable so tests can supply a fake without monkey-
    patching the urllib internals.
    """
    url = urljoin(base_url.rstrip("/") + "/", "v1/projects")
    request = urllib.request.Request(url, method="GET")
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")

    if opener is None:
        opener = _default_opener

    try:
        response = opener(request, timeout_seconds)
    except urllib.error.HTTPError as exc:
        return ProbeResult(
            name="phoenix",
            ok=False,
            detail=f"HTTP {exc.code} from {url}",
            fix_hint="Check the base URL, and confirm the API key if Phoenix is behind auth.",
        )
    except urllib.error.URLError as exc:
        return ProbeResult(
            name="phoenix",
            ok=False,
            detail=f"could not reach {url}: {exc.reason}",
            fix_hint="Confirm Phoenix is running and the URL is correct.",
        )
    except TimeoutError:
        return ProbeResult(
            name="phoenix",
            ok=False,
            detail=f"timed out after {timeout_seconds}s contacting {url}",
            fix_hint="Phoenix may be slow or unreachable from this host.",
        )

    status = getattr(response, "status", None) or response.getcode()
    if 200 <= status < 300:
        return ProbeResult(name="phoenix", ok=True, detail=f"{url} returned {status}")
    return ProbeResult(
        name="phoenix",
        ok=False,
        detail=f"{url} returned {status}",
        fix_hint="Phoenix is up but rejected the request. Check API key and URL path.",
    )


def _default_opener(request: urllib.request.Request, timeout: float) -> Any:
    return urllib.request.urlopen(request, timeout=timeout)


def probe_gemini(
    *,
    api_key: str,
    ping: Callable[[str], None] | None = None,
) -> ProbeResult:
    """
    Issue a one-token Gemini call so an invalid key is caught up-front.

    The default `ping` constructs a `google.genai.Client` and asks for
    a single token. Tests inject a fake to skip the network entirely.
    """
    if ping is None:
        ping = _default_gemini_ping

    try:
        ping(api_key)
    except Exception as exc:
        return ProbeResult(
            name="gemini",
            ok=False,
            detail=str(exc) or exc.__class__.__name__,
            fix_hint="Get a fresh key at https://aistudio.google.com/app/apikey and try again.",
        )
    return ProbeResult(name="gemini", ok=True, detail="1-token ping accepted")


def _default_gemini_ping(api_key: str) -> None:
    try:
        from google import genai
    except ImportError as exc:
        raise RuntimeError("google-genai is not installed; install with the `gemini` extra.") from exc

    client = genai.Client(api_key=api_key)
    client.models.generate_content(
        model="gemini-2.5-flash",
        contents="ping",
        config={"max_output_tokens": 1},
    )


def probe_file_write(target_dir: Path) -> ProbeResult:
    """Confirm the wizard can create and remove a file under `target_dir`."""
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        probe_file = target_dir / ".nengok-write-probe"
        probe_file.write_text("ok", encoding="utf-8")
        probe_file.unlink(missing_ok=True)
    except OSError as exc:
        return ProbeResult(
            name="filesystem",
            ok=False,
            detail=f"could not write to {target_dir}: {exc}",
            fix_hint=f"Create {target_dir} manually or pick a writable --config-path.",
        )
    return ProbeResult(
        name="filesystem", ok=True, detail=f"wrote and removed a probe file under {target_dir}"
    )


def run_probes(
    *,
    phoenix_base_url: str,
    phoenix_api_key: str | None,
    google_api_key: str,
    target_dir: Path,
    phoenix_opener: Callable[[urllib.request.Request, float], Any] | None = None,
    gemini_ping: Callable[[str], None] | None = None,
) -> list[ProbeResult]:
    """Run the connectivity gate in a fixed order."""
    return [
        probe_phoenix_projects(
            base_url=phoenix_base_url,
            api_key=phoenix_api_key,
            opener=phoenix_opener,
        ),
        probe_gemini(api_key=google_api_key, ping=gemini_ping),
        probe_file_write(target_dir),
    ]


def format_probe_summary(results: list[ProbeResult]) -> str:
    """Render the probe table the wizard prints after collecting answers."""
    lines: list[str] = []
    for result in results:
        marker = "PASS" if result.ok else "FAIL"
        lines.append(f"  [{marker}] {result.name}: {result.detail}")
        if not result.ok and result.fix_hint:
            lines.append(f"         fix: {result.fix_hint}")
    return "\n".join(lines)


def all_passed(results: list[ProbeResult]) -> bool:
    return all(r.ok for r in results)


def env_default(name: str) -> str | None:
    value = os.environ.get(name)
    return value.strip() if value else None
