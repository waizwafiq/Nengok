"""
Coverage for the config template bundle and the `nengok config init` command.

Confirms three things: every shipped template renders both verbatim
and with overlays, the `examples/` and `nengok/templates/` copies stay
byte-identical so the GitHub-browsable view never drifts from the
SDK-resident copy, and the CLI subcommand writes the template to disk
without prompting.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from nengok import templates
from nengok.cli import app
from nengok.cli_helpers import _pick_template, render_template

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "examples"


@pytest.mark.parametrize("name", ["local", "cloud", "qa-agent"])
def test_template_is_readable_and_documents_every_section(name: str) -> None:
    body = templates.read_template(name)
    assert "[nengok]" in body
    for marker in (
        "phoenix_base_url",
        "google_api_key",
        "project_identifier",
        "diagnoser_model",
        "gemini_timeout_seconds",
        "circuit_breaker_backoff_seconds",
    ):
        assert marker in body, f"template '{name}' is missing '{marker}'"


@pytest.mark.parametrize("name", ["local", "cloud", "qa-agent"])
def test_packaged_template_matches_repo_root_example(name: str) -> None:
    packaged = templates.read_template(name)
    examples_path = EXAMPLES_DIR / f"config-{name}.toml"
    assert examples_path.is_file(), f"missing example file at {examples_path}"
    on_disk = examples_path.read_text(encoding="utf-8")
    assert packaged == on_disk, (
        f"nengok/templates/config-{name}.toml diverged from examples/config-{name}.toml. "
        "Update both copies so the GitHub-browsable example matches the wheel-bundled copy."
    )


def test_render_template_overlays_user_values() -> None:
    body = render_template(
        "local",
        phoenix_base_url="https://phoenix.example.com",
        project_identifier="my-agent",
        phoenix_api_key="ph-key-123",
        google_api_key="AIza" + "x" * 31,
        agent_runner="my_pkg.module:MyAgent",
    )
    assert 'phoenix_base_url = "https://phoenix.example.com"' in body
    assert 'project_identifier = "my-agent"' in body
    assert 'phoenix_api_key = "ph-key-123"' in body
    assert 'agent_runner = "my_pkg.module:MyAgent"' in body
    assert 'google_api_key = "AIza' in body
    assert "# phoenix_api_key =" not in body
    assert "# google_api_key =" not in body
    assert "# agent_runner =" not in body


def test_render_template_leaves_secrets_commented_when_omitted() -> None:
    body = render_template(
        "local",
        phoenix_base_url="http://localhost:6006",
        project_identifier="my-agent",
    )
    assert "# google_api_key =" in body
    assert "# agent_runner =" in body


def test_render_template_unknown_name_raises() -> None:
    with pytest.raises(ValueError, match="Unknown template"):
        render_template("does-not-exist")


def test_pick_template_uses_qa_when_runner_points_at_qa_agent() -> None:
    assert (
        _pick_template(
            phoenix_base_url="http://localhost:6006",
            project_identifier="qa-agent",
            agent_runner="sample_agent.qa_agent.agent:QAAgent",
        )
        == "qa-agent"
    )


def test_pick_template_uses_cloud_when_url_is_phoenix_cloud() -> None:
    assert (
        _pick_template(
            phoenix_base_url="https://app.phoenix.arize.com",
            project_identifier="travel-planner-agent",
            agent_runner=None,
        )
        == "cloud"
    )


def test_pick_template_defaults_to_local_for_localhost_phoenix() -> None:
    assert (
        _pick_template(
            phoenix_base_url="http://localhost:6006",
            project_identifier="travel-planner-agent",
            agent_runner=None,
        )
        == "local"
    )


def test_config_init_writes_named_template(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    result = CliRunner().invoke(
        app,
        ["config", "init", "--template", "qa-agent", "--config-path", str(config_path)],
    )
    assert result.exit_code == 0, result.output
    body = config_path.read_text(encoding="utf-8")
    assert 'project_identifier = "qa-agent"' in body
    assert 'agent_runner = "sample_agent.qa_agent.agent:QAAgent"' in body
    assert "Wrote " in result.output


def test_config_init_rejects_unknown_template(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    result = CliRunner().invoke(
        app,
        ["config", "init", "--template", "nope", "--config-path", str(config_path)],
    )
    assert result.exit_code == 2
    assert "Unknown template" in result.output
    assert not config_path.exists()


def test_config_init_refuses_to_overwrite_existing_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("# existing\n", encoding="utf-8")
    result = CliRunner().invoke(
        app,
        ["config", "init", "--template", "local", "--config-path", str(config_path)],
    )
    assert result.exit_code == 2
    assert "already exists" in result.output
    assert config_path.read_text(encoding="utf-8") == "# existing\n"


def test_config_init_force_overwrites_existing_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("# existing\n", encoding="utf-8")
    result = CliRunner().invoke(
        app,
        [
            "config",
            "init",
            "--template",
            "local",
            "--config-path",
            str(config_path),
            "--force",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "# existing" not in config_path.read_text(encoding="utf-8")
