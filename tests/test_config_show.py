"""Coverage for `nengok config show` and the masking helper it depends on."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from nengok.cli import app
from nengok.cli_helpers import format_config_for_display, mask_secret
from nengok.config import NengokConfig

SAMPLE_API_KEY = "AIzaSyD1234567890abcdefghijklmnopqrstuvwx"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "<unset>"),
        ("", "****"),
        ("short", "****"),
        ("nine-char", "****"),
        ("0123456789", "0123****6789"),
        (SAMPLE_API_KEY, f"{SAMPLE_API_KEY[:4]}****{SAMPLE_API_KEY[-4:]}"),
    ],
)
def test_mask_secret_format(value: str | None, expected: str) -> None:
    assert mask_secret(value) == expected


def test_format_config_masks_known_secret_fields(tmp_path: Path) -> None:
    config = NengokConfig(
        phoenix_base_url="http://localhost:6006",
        phoenix_api_key="phoenix-key-1234567890",
        google_api_key=SAMPLE_API_KEY,
        dashboard_auth_token="token-abcdef-987654321",
        project_identifier="travel-planner-agent",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
    )

    rendered = format_config_for_display(config)

    assert SAMPLE_API_KEY not in rendered
    assert "phoenix-key-1234567890" not in rendered
    assert "token-abcdef-987654321" not in rendered
    assert "google_api_key = AIza****uvwx" in rendered
    assert "phoenix_api_key = phoe****7890" in rendered
    assert "dashboard_auth_token = toke****4321" in rendered
    assert "phoenix_base_url = 'http://localhost:6006'" in rendered


def test_format_config_shows_unset_for_none_secrets(tmp_path: Path) -> None:
    config = NengokConfig(
        phoenix_base_url="http://localhost:6006",
        google_api_key="any",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
    )

    rendered = format_config_for_display(config)
    assert "phoenix_api_key = ****" in rendered or "phoenix_api_key = <unset>" in rendered
    assert "dashboard_auth_token = <unset>" in rendered


def _write_config(path: Path) -> None:
    path.write_text(
        "[nengok]\n"
        'phoenix_base_url = "http://localhost:6006"\n'
        f'google_api_key = "{SAMPLE_API_KEY}"\n'
        'phoenix_api_key = "phoenix-key-abcdefghij"\n'
        'project_identifier = "travel-planner-agent"\n'
        'dashboard_auth_token = "dashboard-token-zyxwvutsrq"\n',
        encoding="utf-8",
    )


def _isolate_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Strip ambient env vars and silence dotenv so the test only sees `tmp_path`."""
    monkeypatch.setattr("nengok.cli.load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.chdir(tmp_path)
    for env in (
        "PHOENIX_BASE_URL",
        "PHOENIX_API_KEY",
        "GOOGLE_API_KEY",
        "NENGOK_PROJECT",
        "NENGOK_DASHBOARD_AUTH_TOKEN",
        "NENGOK_ARTIFACTS_DIR",
        "NENGOK_STATE_DB",
    ):
        monkeypatch.delenv(env, raising=False)


def test_config_show_prints_masked_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_env(monkeypatch, tmp_path)
    config_path = tmp_path / "config.toml"
    _write_config(config_path)
    monkeypatch.setenv("NENGOK_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("NENGOK_STATE_DB", str(tmp_path / "state.db"))

    runner = CliRunner()
    result = runner.invoke(app, ["config", "show", "--config-path", str(config_path)])

    assert result.exit_code == 0, result.output
    assert SAMPLE_API_KEY not in result.output
    assert "phoenix-key-abcdefghij" not in result.output
    assert "dashboard-token-zyxwvutsrq" not in result.output
    assert "google_api_key = AIza****uvwx" in result.output
    assert "phoenix_api_key = phoe****ghij" in result.output
    assert "dashboard_auth_token = dash****tsrq" in result.output
    assert f"# Loaded from {config_path}" in result.output


def test_config_show_exits_2_when_config_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_env(monkeypatch, tmp_path)
    config_path = tmp_path / "config.toml"
    config_path.write_text("[nengok]\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["config", "show", "--config-path", str(config_path)])

    assert result.exit_code == 2
    assert "Phoenix base URL not configured" in result.output
