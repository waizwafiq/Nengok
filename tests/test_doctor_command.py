"""
Coverage for the `nengok doctor` health check.

Tests are split into two layers: the individual probes in
`nengok.diagnostics.*` (driven by tiny fakes for Phoenix, Gemini, and
the file system) and the Typer-driven `nengok doctor` command (which
runs the probes against an isolated config and captures exit codes
and report formatting).
"""

from __future__ import annotations

import email.message
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from nengok import diagnostics
from nengok.cli import app
from nengok.config import NengokConfig
from nengok.diagnostics import ProbeResult, ProbeStatus, phoenix_project_probe
from nengok.diagnostics import agent_runner_probe as agent_runner_module
from nengok.diagnostics.baseline_prompt_probe import probe_baseline_prompt
from nengok.diagnostics.config_probe import probe_config_file
from nengok.diagnostics.gemini_probe import probe_gemini
from nengok.diagnostics.phoenix_probe import probe_phoenix


class _FakeResponse:
    def __init__(self, status: int, body: bytes | None = None) -> None:
        self.status = status
        self._body = body

    def getcode(self) -> int:
        return self.status

    def read(self) -> bytes:
        return self._body or b""


def _make_config(tmp_path: Path, **overrides: Any) -> NengokConfig:
    defaults: dict[str, Any] = {
        "phoenix_base_url": "http://localhost:6006",
        "google_api_key": "AIzaTEST-key-for-unit-tests" + "x" * 20,
        "project_identifier": "travel-planner-agent",
        "artifacts_dir": tmp_path / "artifacts",
        "state_db_path": tmp_path / "state.db",
    }
    defaults.update(overrides)
    return NengokConfig.load(config_path=tmp_path / "missing.toml", **defaults)


def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "PHOENIX_BASE_URL",
        "PHOENIX_API_KEY",
        "GOOGLE_API_KEY",
        "NENGOK_PROJECT",
    ):
        monkeypatch.delenv(key, raising=False)


def _disable_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nengok.cli.load_dotenv", lambda *_a, **_kw: False)


# Individual probes


def test_probe_config_file_reports_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("nengok.diagnostics.config_probe.DEFAULT_CONFIG_PATH", tmp_path / "absent.toml")
    config = _make_config(tmp_path)
    result = probe_config_file(config)
    assert result.failed
    assert "absent.toml" in result.detail


def test_probe_config_file_reports_ok_when_present(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[nengok]\n", encoding="utf-8")
    monkeypatch.setattr("nengok.diagnostics.config_probe.DEFAULT_CONFIG_PATH", path)
    result = probe_config_file(_make_config(tmp_path))
    assert result.ok
    assert "last modified" in result.detail


def _passing_opener(_request: urllib.request.Request, _timeout: float) -> _FakeResponse:
    return _FakeResponse(200, body=json.dumps({"data": [{"id": "a"}, {"id": "b"}]}).encode())


def _refused_opener(_request: urllib.request.Request, _timeout: float) -> _FakeResponse:
    raise urllib.error.URLError("connection refused")


def _http_404_opener(_request: urllib.request.Request, _timeout: float) -> _FakeResponse:
    raise urllib.error.HTTPError(
        url="http://localhost:6006/v1/projects",
        code=404,
        msg="Not Found",
        hdrs=email.message.Message(),
        fp=None,
    )


def test_probe_phoenix_ok(tmp_path: Path) -> None:
    result = probe_phoenix(_make_config(tmp_path), opener=_passing_opener)
    assert result.ok
    assert "2 projects" in result.detail


def test_probe_phoenix_reports_refused_connection(tmp_path: Path) -> None:
    result = probe_phoenix(_make_config(tmp_path), opener=_refused_opener)
    assert result.failed
    assert "could not reach" in result.detail


def test_probe_phoenix_reports_http_error(tmp_path: Path) -> None:
    result = probe_phoenix(_make_config(tmp_path), opener=_http_404_opener)
    assert result.failed
    assert "404" in result.detail


class _StubWrapper:
    def __init__(self, spans: list[Any] | None = None, raises: Exception | None = None) -> None:
        self._spans = spans or []
        self._raises = raises

    def get_spans(self, *, project_identifier: str, limit: int) -> list[Any]:
        del project_identifier, limit
        if self._raises is not None:
            raise self._raises
        return self._spans


def test_probe_phoenix_project_ok(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    wrapper = _StubWrapper(spans=[object(), object(), object()])
    result = phoenix_project_probe.probe_phoenix_project(config, wrapper_factory=lambda _c: wrapper)
    assert result.ok
    assert "3 recent spans" in result.detail


def test_probe_phoenix_project_warns_on_empty(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    wrapper = _StubWrapper(spans=[])
    result = phoenix_project_probe.probe_phoenix_project(config, wrapper_factory=lambda _c: wrapper)
    assert result.warned
    assert "no spans yet" in result.detail


def test_probe_phoenix_project_fails_when_wrapper_raises(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    wrapper = _StubWrapper(raises=RuntimeError("project missing"))
    result = phoenix_project_probe.probe_phoenix_project(config, wrapper_factory=lambda _c: wrapper)
    assert result.failed
    assert "project missing" in result.detail


def test_probe_gemini_ok(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    result = probe_gemini(config, ping=lambda _key: None)
    assert result.ok
    assert "ms ping" in result.detail


def test_probe_gemini_fails_on_rejected_key(tmp_path: Path) -> None:
    config = _make_config(tmp_path)

    def _reject(_key: str) -> None:
        raise RuntimeError("API_KEY_INVALID")

    result = probe_gemini(config, ping=_reject)
    assert result.failed
    assert "API_KEY_INVALID" in result.detail


def test_probe_baseline_prompt_unconfigured_is_ok(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    result = probe_baseline_prompt(config)
    assert result.ok
    assert "not configured" in result.detail


def test_probe_baseline_prompt_ok_when_readable(tmp_path: Path) -> None:
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("you are a helpful agent", encoding="utf-8")
    config = _make_config(tmp_path, baseline_prompt_path=prompt_path)
    result = probe_baseline_prompt(config)
    assert result.ok
    assert "KB" in result.detail


def test_probe_agent_runner_uses_registered_default(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    result = agent_runner_module.probe_agent_runner(config)
    assert result.ok
    assert "registered runner" in result.detail


def test_probe_agent_runner_loadable_dotted_path(tmp_path: Path) -> None:
    runner_path = "nengok.runners.agent_runner:sample_agent_runner"
    config = _make_config(tmp_path, agent_runner=runner_path)
    result = agent_runner_module.probe_agent_runner(config)
    assert result.ok
    assert runner_path in result.detail


def test_probe_agent_runner_reports_unloadable(tmp_path: Path) -> None:
    config = _make_config(tmp_path, agent_runner="nengok.runners.agent_runner:does_not_exist")
    result = agent_runner_module.probe_agent_runner(config)
    assert result.failed
    assert "does_not_exist" in result.detail


# CLI integration


def _stub_default_probes(
    *,
    project_factory: Any | None = None,
    gemini_ping: Any | None = None,
    phoenix_opener: Any | None = None,
) -> tuple[Any, ...]:
    if project_factory is None:
        project_factory = lambda _c: _StubWrapper(spans=[object(), object()])  # noqa: E731
    if gemini_ping is None:
        gemini_ping = lambda _key: None  # noqa: E731
    if phoenix_opener is None:
        phoenix_opener = _passing_opener

    def _phoenix(config: NengokConfig) -> ProbeResult:
        return probe_phoenix(config, opener=phoenix_opener)

    def _phoenix_project(config: NengokConfig) -> ProbeResult:
        return phoenix_project_probe.probe_phoenix_project(config, wrapper_factory=project_factory)

    def _gemini(config: NengokConfig) -> ProbeResult:
        return probe_gemini(config, ping=gemini_ping)

    return (
        diagnostics.probe_config_file,
        _phoenix,
        _phoenix_project,
        _gemini,
        diagnostics.probe_baseline_prompt,
        diagnostics.probe_agent_runner,
    )


def _patch_doctor(monkeypatch: pytest.MonkeyPatch, probes: tuple[Any, ...]) -> None:
    monkeypatch.setattr("nengok.cli.DEFAULT_PROBES", probes)


def _patch_load(monkeypatch: pytest.MonkeyPatch, config: NengokConfig) -> None:
    monkeypatch.setattr("nengok.cli.NengokConfig.load", classmethod(lambda _cls: config))


def test_doctor_happy_path_exits_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_env(monkeypatch)
    _disable_dotenv(monkeypatch)
    config_file = tmp_path / "config.toml"
    config_file.write_text("[nengok]\n", encoding="utf-8")
    monkeypatch.setattr("nengok.diagnostics.config_probe.DEFAULT_CONFIG_PATH", config_file)

    config = _make_config(tmp_path)
    _patch_load(monkeypatch, config)
    _patch_doctor(monkeypatch, _stub_default_probes())

    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "Nengok v" in result.output
    assert "[ok] phoenix" in result.output


def test_doctor_fail_when_any_probe_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_env(monkeypatch)
    _disable_dotenv(monkeypatch)
    config_file = tmp_path / "config.toml"
    config_file.write_text("[nengok]\n", encoding="utf-8")
    monkeypatch.setattr("nengok.diagnostics.config_probe.DEFAULT_CONFIG_PATH", config_file)

    config = _make_config(tmp_path)
    _patch_load(monkeypatch, config)
    _patch_doctor(monkeypatch, _stub_default_probes(phoenix_opener=_refused_opener))

    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "[fail] phoenix" in result.output
    assert "Fix:" in result.output


def test_doctor_strict_promotes_warn_to_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_env(monkeypatch)
    _disable_dotenv(monkeypatch)
    config_file = tmp_path / "config.toml"
    config_file.write_text("[nengok]\n", encoding="utf-8")
    monkeypatch.setattr("nengok.diagnostics.config_probe.DEFAULT_CONFIG_PATH", config_file)

    config = _make_config(tmp_path)
    _patch_load(monkeypatch, config)
    empty_project = _stub_default_probes(project_factory=lambda _c: _StubWrapper(spans=[]))
    _patch_doctor(monkeypatch, empty_project)

    lax = CliRunner().invoke(app, ["doctor"])
    assert lax.exit_code == 0
    assert "[warn] phoenix-project" in lax.output

    strict = CliRunner().invoke(app, ["doctor", "--strict"])
    assert strict.exit_code == 1


def test_doctor_json_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_env(monkeypatch)
    _disable_dotenv(monkeypatch)
    config_file = tmp_path / "config.toml"
    config_file.write_text("[nengok]\n", encoding="utf-8")
    monkeypatch.setattr("nengok.diagnostics.config_probe.DEFAULT_CONFIG_PATH", config_file)

    config = _make_config(tmp_path)
    _patch_load(monkeypatch, config)
    _patch_doctor(monkeypatch, _stub_default_probes())

    result = CliRunner().invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "nengok_version" in payload
    names = [r["name"] for r in payload["results"]]
    assert "phoenix" in names
    assert "gemini" in names


def test_doctor_missing_config_exits_one(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolate_env(monkeypatch)
    _disable_dotenv(monkeypatch)

    def _raise_config(_cls: type[NengokConfig]) -> NengokConfig:
        from nengok.errors import ConfigError

        raise ConfigError("Phoenix base URL not configured.")

    monkeypatch.setattr("nengok.cli.NengokConfig.load", classmethod(_raise_config))

    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "[fail] config" in result.output


def test_probe_raising_unexpectedly_is_caught(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_env(monkeypatch)
    _disable_dotenv(monkeypatch)
    config_file = tmp_path / "config.toml"
    config_file.write_text("[nengok]\n", encoding="utf-8")
    monkeypatch.setattr("nengok.diagnostics.config_probe.DEFAULT_CONFIG_PATH", config_file)

    def _exploding_probe(_config: NengokConfig) -> ProbeResult:
        raise RuntimeError("unexpected blowup")

    _exploding_probe.__name__ = "exploding"

    config = _make_config(tmp_path)
    _patch_load(monkeypatch, config)
    _patch_doctor(
        monkeypatch,
        (
            diagnostics.probe_config_file,
            _exploding_probe,
        ),
    )

    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "[fail] exploding" in result.output
    assert "unexpected blowup" in result.output


def test_probe_result_to_dict_round_trip() -> None:
    result = ProbeResult(
        name="gemini",
        status=ProbeStatus.OK,
        detail="auth ok",
    )
    payload = result.to_dict()
    assert payload == {
        "name": "gemini",
        "status": "ok",
        "detail": "auth ok",
        "fix_hint": None,
    }


def test_run_probes_uses_callable_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Smoke test that we surface the exception class name in failures."""
    from nengok.cli import _run_probes

    def _boom(_config: NengokConfig) -> ProbeResult:
        raise ValueError("oops")

    _boom.__name__ = "named_probe"
    config = _make_config(tmp_path)
    results = _run_probes(config=config, probes=(_boom,))
    assert results[0].name == "named_probe"
    assert "ValueError" in results[0].detail


def test_doctor_handles_unicode_in_detail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Make sure the JSON serializer survives non-ASCII detail text."""
    _isolate_env(monkeypatch)
    _disable_dotenv(monkeypatch)
    config_file = tmp_path / "config.toml"
    config_file.write_text("[nengok]\n", encoding="utf-8")
    monkeypatch.setattr("nengok.diagnostics.config_probe.DEFAULT_CONFIG_PATH", config_file)

    def _utf8_probe(_config: NengokConfig) -> ProbeResult:
        return ProbeResult(name="utf8", status=ProbeStatus.OK, detail="naïve café")

    config = _make_config(tmp_path)
    _patch_load(monkeypatch, config)
    _patch_doctor(monkeypatch, (_utf8_probe,))

    with patch("nengok.cli.typer.echo") as echo:
        runner_result = CliRunner().invoke(app, ["doctor", "--json"])
    assert runner_result.exit_code == 0
    echo.assert_called()
