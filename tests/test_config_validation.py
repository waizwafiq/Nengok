"""
Coverage for `NengokConfig.validate()` and the CLI's ConfigError -> exit-2 wiring.

Each test exercises one rejection path so a regression points at the
exact field that broke.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nengok.cli import app
from nengok.config import NengokConfig
from nengok.errors import ConfigError


def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "PHOENIX_BASE_URL",
        "PHOENIX_API_KEY",
        "GOOGLE_API_KEY",
        "GOOGLE_GENAI_USE_VERTEXAI",
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_LOCATION",
        "NENGOK_PROJECT",
        "NENGOK_BASELINE_PROMPT_PATH",
    ):
        monkeypatch.delenv(key, raising=False)


def _base_kwargs(tmp_path: Path) -> dict[str, object]:
    return {
        "config_path": tmp_path / "missing.toml",
        "phoenix_base_url": "http://localhost:6006",
        "google_api_key": "AIzaTEST",
        "artifacts_dir": tmp_path / "artifacts",
        "state_db_path": tmp_path / "state.db",
    }


def test_missing_google_api_key_raises_with_actionable_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate_env(monkeypatch)
    kwargs = _base_kwargs(tmp_path)
    kwargs["google_api_key"] = None
    with pytest.raises(ConfigError) as exc_info:
        NengokConfig.load(**kwargs)
    message = str(exc_info.value)
    assert "GOOGLE_API_KEY" in message
    assert "aistudio.google.com/app/apikey" in message


def test_vertex_without_project_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_env(monkeypatch)
    kwargs = _base_kwargs(tmp_path)
    kwargs["gemini_use_vertex"] = True
    kwargs["google_api_key"] = None
    with pytest.raises(ConfigError, match="project"):
        NengokConfig.load(**kwargs)


def test_vertex_with_project_passes_without_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate_env(monkeypatch)
    kwargs = _base_kwargs(tmp_path)
    kwargs["gemini_use_vertex"] = True
    kwargs["vertex_project"] = "my-proj"
    kwargs["google_api_key"] = None
    config = NengokConfig.load(**kwargs)
    assert config.gemini_use_vertex is True
    assert config.vertex_project == "my-proj"
    assert config.google_api_key is None


def test_vertex_project_from_env_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "env-proj")
    kwargs = _base_kwargs(tmp_path)
    kwargs["gemini_use_vertex"] = True
    kwargs["google_api_key"] = None
    config = NengokConfig.load(**kwargs)
    assert config.vertex_project == "env-proj"


def test_ai_studio_without_api_key_still_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate_env(monkeypatch)
    kwargs = _base_kwargs(tmp_path)
    kwargs["gemini_use_vertex"] = False
    kwargs["google_api_key"] = None
    with pytest.raises(ConfigError, match="GOOGLE_API_KEY"):
        NengokConfig.load(**kwargs)


def test_malformed_phoenix_url_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_env(monkeypatch)
    kwargs = _base_kwargs(tmp_path)
    kwargs["phoenix_base_url"] = "not-a-url"
    with pytest.raises(ConfigError, match="phoenix_base_url"):
        NengokConfig.load(**kwargs)


def test_empty_project_identifier_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_env(monkeypatch)
    kwargs = _base_kwargs(tmp_path)
    kwargs["project_identifier"] = ""
    with pytest.raises(ConfigError, match="phoenix_project_name"):
        NengokConfig.load(**kwargs)


def test_sample_agent_project_emits_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _isolate_env(monkeypatch)
    kwargs = _base_kwargs(tmp_path)
    kwargs["project_identifier"] = "travel-planner-agent"
    with caplog.at_level(logging.WARNING, logger="nengok.config"):
        NengokConfig.load(**kwargs)
    assert any("travel-planner-agent" in record.message for record in caplog.records)


def test_baseline_prompt_path_missing_file_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_env(monkeypatch)
    kwargs = _base_kwargs(tmp_path)
    kwargs["baseline_prompt_path"] = tmp_path / "does-not-exist.md"
    with pytest.raises(ConfigError, match="baseline_prompt_path"):
        NengokConfig.load(**kwargs)


def test_baseline_prompt_path_directory_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_env(monkeypatch)
    kwargs = _base_kwargs(tmp_path)
    kwargs["baseline_prompt_path"] = tmp_path
    with pytest.raises(ConfigError, match="not a file"):
        NengokConfig.load(**kwargs)


def test_baseline_prompt_path_valid_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_env(monkeypatch)
    prompt = tmp_path / "prompt.md"
    prompt.write_text("You are a helpful assistant.")
    kwargs = _base_kwargs(tmp_path)
    kwargs["baseline_prompt_path"] = prompt
    config = NengokConfig.load(**kwargs)
    assert config.baseline_prompt_path == prompt


def test_gemini_timeout_out_of_range_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_env(monkeypatch)
    kwargs = _base_kwargs(tmp_path)
    kwargs["gemini_timeout_seconds"] = 0.5
    with pytest.raises(ConfigError, match="gemini_timeout_seconds"):
        NengokConfig.load(**kwargs)


def test_regression_pass_threshold_above_one_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate_env(monkeypatch)
    kwargs = _base_kwargs(tmp_path)
    kwargs["regression_pass_threshold"] = 1.5
    with pytest.raises(ConfigError, match="regression_pass_threshold"):
        NengokConfig.load(**kwargs)


def test_span_limit_zero_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_env(monkeypatch)
    kwargs = _base_kwargs(tmp_path)
    kwargs["span_limit"] = 0
    with pytest.raises(ConfigError, match="span_limit"):
        NengokConfig.load(**kwargs)


def test_dashboard_port_out_of_range_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_env(monkeypatch)
    kwargs = _base_kwargs(tmp_path)
    kwargs["dashboard_port"] = 99_999
    with pytest.raises(ConfigError, match="dashboard_port"):
        NengokConfig.load(**kwargs)


def test_happy_path_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_env(monkeypatch)
    config = NengokConfig.load(**_base_kwargs(tmp_path))
    assert config.phoenix_base_url == "http://localhost:6006"
    assert config.google_api_key == "AIzaTEST"


def _disable_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    def _noop(*_args: object, **_kwargs: object) -> bool:
        return False

    monkeypatch.setattr("nengok.cli.load_dotenv", _noop)


def test_cli_run_exits_two_on_missing_google_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_env(monkeypatch)
    _disable_dotenv(monkeypatch)
    monkeypatch.setenv("PHOENIX_BASE_URL", "http://localhost:6006")
    runner = CliRunner()
    result = runner.invoke(app, ["run", "--skip-preflight"])
    assert result.exit_code == 2
    assert "GOOGLE_API_KEY" in result.output


def test_cli_dashboard_exits_two_on_malformed_phoenix_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_env(monkeypatch)
    _disable_dotenv(monkeypatch)
    monkeypatch.setenv("PHOENIX_BASE_URL", "not-a-url")
    monkeypatch.setenv("GOOGLE_API_KEY", "AIzaTEST")
    runner = CliRunner()
    result = runner.invoke(app, ["dashboard", "--no-browser"])
    assert result.exit_code == 2
    assert "phoenix_base_url" in result.output
