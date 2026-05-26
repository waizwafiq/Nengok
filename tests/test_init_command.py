"""
Coverage for the `nengok init` wizard.

Tests are split into two groups: pure functions in `nengok.init_wizard`
(prompts, probes, formatting) and the CliRunner-driven integration
through `nengok.cli.init`. The HTTP and Gemini layers are stubbed so
the test suite never touches the network.
"""

from __future__ import annotations

import email.message
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import click
import pytest
from typer.testing import CliRunner

from nengok import init_wizard
from nengok.cli import app


class _FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status

    def getcode(self) -> int:
        return self.status


def _passing_opener(_request: urllib.request.Request, _timeout: float) -> _FakeResponse:
    return _FakeResponse(200)


def _failing_opener(_request: urllib.request.Request, _timeout: float) -> _FakeResponse:
    raise urllib.error.URLError("connection refused")


def _http_404_opener(_request: urllib.request.Request, _timeout: float) -> _FakeResponse:
    raise urllib.error.HTTPError(
        url="http://phoenix/v1/projects",
        code=404,
        msg="Not Found",
        hdrs=email.message.Message(),
        fp=None,
    )


def _accepting_gemini_ping(_api_key: str) -> None:
    return None


def _rejecting_gemini_ping(_api_key: str) -> None:
    raise RuntimeError("API_KEY_INVALID")


def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "PHOENIX_BASE_URL",
        "PHOENIX_API_KEY",
        "GOOGLE_API_KEY",
        "NENGOK_PROJECT",
    ):
        monkeypatch.delenv(key, raising=False)


def _disable_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    def _noop(*_args: object, **_kwargs: object) -> bool:
        return False

    monkeypatch.setattr("nengok.cli.load_dotenv", _noop)


# Pure wizard functions


def test_looks_like_google_api_key_accepts_valid_prefix() -> None:
    assert init_wizard.looks_like_google_api_key("AIza" + "x" * 31)


def test_looks_like_google_api_key_rejects_short_and_wrong_prefix() -> None:
    assert not init_wizard.looks_like_google_api_key("AIza_short")
    assert not init_wizard.looks_like_google_api_key("sk-totally-wrong-prefix" + "x" * 20)


def test_probe_phoenix_ok_on_2xx() -> None:
    result = init_wizard.probe_phoenix_projects(
        base_url="http://phoenix.local:6006",
        api_key=None,
        opener=_passing_opener,
    )
    assert result.ok
    assert result.name == "phoenix"


def test_probe_phoenix_records_url_error() -> None:
    result = init_wizard.probe_phoenix_projects(
        base_url="http://phoenix.local:6006",
        api_key=None,
        opener=_failing_opener,
    )
    assert not result.ok
    assert "connection refused" in result.detail
    assert result.fix_hint is not None


def test_probe_phoenix_records_http_error() -> None:
    result = init_wizard.probe_phoenix_projects(
        base_url="http://phoenix.local:6006",
        api_key=None,
        opener=_http_404_opener,
    )
    assert not result.ok
    assert "HTTP 404" in result.detail


def test_probe_gemini_ok_when_ping_returns() -> None:
    result = init_wizard.probe_gemini(api_key="AIzaTEST" + "x" * 24, ping=_accepting_gemini_ping)
    assert result.ok


def test_probe_gemini_records_ping_error() -> None:
    result = init_wizard.probe_gemini(api_key="AIzaTEST" + "x" * 24, ping=_rejecting_gemini_ping)
    assert not result.ok
    assert "API_KEY_INVALID" in result.detail


def test_probe_file_write_succeeds_under_tmp(tmp_path: Path) -> None:
    result = init_wizard.probe_file_write(tmp_path / "nengok-test")
    assert result.ok
    assert not (tmp_path / "nengok-test" / ".nengok-write-probe").exists()


def test_format_probe_summary_marks_pass_and_fail() -> None:
    results = [
        init_wizard.ProbeResult(name="phoenix", ok=True, detail="up"),
        init_wizard.ProbeResult(name="gemini", ok=False, detail="bad key", fix_hint="rotate it"),
    ]
    text = init_wizard.format_probe_summary(results)
    assert "[PASS] phoenix" in text
    assert "[FAIL] gemini" in text
    assert "fix: rotate it" in text


def test_prompt_google_api_key_retries_then_accepts() -> None:
    valid_key = "AIza" + "x" * 31
    answers: Iterator[str] = iter(["badkey", valid_key])
    probe_calls: list[str] = []

    def _ask(*_args: Any, **_kwargs: Any) -> str:
        return next(answers)

    def _probe(key: str) -> init_wizard.ProbeResult:
        probe_calls.append(key)
        return init_wizard.ProbeResult(name="gemini", ok=True, detail="ok")

    captured: list[str] = []

    def _echo(message: str) -> None:
        captured.append(message)

    result = init_wizard.prompt_google_api_key(probe=_probe, ask=_ask, echo=_echo)
    assert result == valid_key
    assert probe_calls == [valid_key]
    assert any("doesn't look like" in line for line in captured)


def test_prompt_google_api_key_aborts_after_max_attempts() -> None:
    answers: Iterator[str] = iter(["bad1", "bad2", "bad3"])

    def _ask(*_args: Any, **_kwargs: Any) -> str:
        return next(answers)

    def _probe(_key: str) -> init_wizard.ProbeResult:
        return init_wizard.ProbeResult(name="gemini", ok=False, detail="rejected")

    with pytest.raises(click.Abort):
        init_wizard.prompt_google_api_key(probe=_probe, ask=_ask, echo=lambda _msg: None)


# CLI integration


def _stub_probes(monkeypatch: pytest.MonkeyPatch, *, phoenix_ok: bool, gemini_ok: bool) -> None:
    def _phoenix(
        *, base_url: str, api_key: str | None, opener: Any = None, timeout_seconds: float = 5.0
    ) -> init_wizard.ProbeResult:
        del base_url, api_key, opener, timeout_seconds
        return init_wizard.ProbeResult(
            name="phoenix",
            ok=phoenix_ok,
            detail="ok" if phoenix_ok else "unreachable",
            fix_hint=None if phoenix_ok else "start Phoenix",
        )

    def _gemini(*, api_key: str, ping: Any = None) -> init_wizard.ProbeResult:
        del api_key, ping
        return init_wizard.ProbeResult(
            name="gemini",
            ok=gemini_ok,
            detail="ok" if gemini_ok else "rejected",
            fix_hint=None if gemini_ok else "rotate key",
        )

    monkeypatch.setattr(init_wizard, "probe_phoenix_projects", _phoenix)
    monkeypatch.setattr(init_wizard, "probe_gemini", _gemini)


def test_init_non_interactive_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_env(monkeypatch)
    _disable_dotenv(monkeypatch)
    _stub_probes(monkeypatch, phoenix_ok=True, gemini_ok=True)

    config_path = tmp_path / "config.toml"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "init",
            "--phoenix-url",
            "http://localhost:6006",
            "--google-api-key",
            "AIza" + "x" * 31,
            "--project",
            "my-agent",
            "--agent-runner",
            "my_pkg.module:MyAgent",
            "--config-path",
            str(config_path),
            "--non-interactive",
        ],
    )
    assert result.exit_code == 0, result.output
    body = config_path.read_text()
    assert 'phoenix_base_url = "http://localhost:6006"' in body
    assert 'project_identifier = "my-agent"' in body
    assert 'agent_runner = "my_pkg.module:MyAgent"' in body
    assert 'google_api_key = "AIza' in body


def test_init_non_interactive_missing_required_exits_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate_env(monkeypatch)
    _disable_dotenv(monkeypatch)
    config_path = tmp_path / "config.toml"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "init",
            "--phoenix-url",
            "http://localhost:6006",
            "--config-path",
            str(config_path),
            "--non-interactive",
        ],
    )
    assert result.exit_code == 2
    assert "--google-api-key" in result.output
    assert not config_path.exists()


def test_init_probe_failure_blocks_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_env(monkeypatch)
    _disable_dotenv(monkeypatch)
    _stub_probes(monkeypatch, phoenix_ok=False, gemini_ok=True)

    config_path = tmp_path / "config.toml"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "init",
            "--phoenix-url",
            "http://localhost:6006",
            "--google-api-key",
            "AIza" + "x" * 31,
            "--project",
            "my-agent",
            "--config-path",
            str(config_path),
            "--non-interactive",
        ],
    )
    assert result.exit_code == 1
    assert "[FAIL] phoenix" in result.output
    assert not config_path.exists()


def test_init_force_writes_even_on_probe_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_env(monkeypatch)
    _disable_dotenv(monkeypatch)
    _stub_probes(monkeypatch, phoenix_ok=False, gemini_ok=True)

    config_path = tmp_path / "config.toml"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "init",
            "--phoenix-url",
            "http://localhost:6006",
            "--google-api-key",
            "AIza" + "x" * 31,
            "--project",
            "my-agent",
            "--config-path",
            str(config_path),
            "--non-interactive",
            "--force",
        ],
    )
    assert result.exit_code == 0, result.output
    assert config_path.exists()


def test_init_interactive_prompts_for_missing_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_env(monkeypatch)
    _disable_dotenv(monkeypatch)
    _stub_probes(monkeypatch, phoenix_ok=True, gemini_ok=True)
    monkeypatch.setattr(init_wizard, "detect_local_phoenix", lambda *, timeout_seconds=2.0: True)

    config_path = tmp_path / "config.toml"
    valid_key = "AIza" + "x" * 31
    stdin = (
        "\n".join(
            [
                "3",  # local phoenix
                valid_key,  # GOOGLE_API_KEY prompt
                "my-agent",  # project name
                "1",  # bundled runner
            ]
        )
        + "\n"
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["init", "--config-path", str(config_path)],
        input=stdin,
    )
    assert result.exit_code == 0, result.output
    body = config_path.read_text()
    assert 'phoenix_base_url = "http://localhost:6006"' in body
    assert 'project_identifier = "my-agent"' in body
    assert "# agent_runner =" in body
