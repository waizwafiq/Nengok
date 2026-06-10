"""Config parsing and validation for multi-project monitoring."""

from __future__ import annotations

from pathlib import Path

import pytest

from nengok.config import NengokConfig
from nengok.errors import ConfigError


def _kwargs(tmp_path: Path) -> dict:
    return {
        "config_path": tmp_path / "missing.toml",
        "phoenix_base_url": "http://localhost:6006",
        "google_api_key": "AIzaTEST",
        "artifacts_dir": tmp_path / "artifacts",
        "state_db_path": tmp_path / "state.db",
    }


def test_empty_list_resolves_to_single_project(tmp_path: Path) -> None:
    config = NengokConfig.load(**_kwargs(tmp_path), project_identifier="travel-planner-agent")
    assert config.resolved_project_identifiers() == ["travel-planner-agent"]


def test_explicit_list_wins_over_single_project(tmp_path: Path) -> None:
    config = NengokConfig.load(
        **_kwargs(tmp_path),
        project_identifier="travel-planner-agent",
        project_identifiers=["travel-planner-agent", "qa-agent"],
    )
    assert config.resolved_project_identifiers() == ["travel-planner-agent", "qa-agent"]


def test_env_var_parses_comma_separated_projects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NENGOK_PROJECTS", "travel-planner-agent, qa-agent")
    config = NengokConfig.load(**_kwargs(tmp_path))
    assert config.project_identifiers == ["travel-planner-agent", "qa-agent"]


def test_empty_entry_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="empty entry"):
        NengokConfig.load(**_kwargs(tmp_path), project_identifiers=["a", " "])


def test_duplicate_entries_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="duplicates"):
        NengokConfig.load(**_kwargs(tmp_path), project_identifiers=["a", "b", "a"])


def test_per_project_runner_spec_is_validated(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"agent_runners\['qa-agent'\]"):
        NengokConfig.load(**_kwargs(tmp_path), agent_runners={"qa-agent": "not-a-spec"})


def test_runner_spec_for_falls_back_to_agent_runner(tmp_path: Path) -> None:
    config = NengokConfig.load(
        **_kwargs(tmp_path),
        agent_runner="nengok.runners.sample_agent_runner:SampleAgentRunner",
        agent_runners={"qa-agent": "my_pkg.runner:QaRunner"},
    )
    assert config.runner_spec_for("qa-agent") == "my_pkg.runner:QaRunner"
    assert config.runner_spec_for("other") == "nengok.runners.sample_agent_runner:SampleAgentRunner"
