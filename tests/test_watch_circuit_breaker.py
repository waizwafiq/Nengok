"""Watch loop pauses after consecutive stage failures and writes an incident."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from nengok import cli as cli_module


class _AlwaysFailsOrchestrator:
    def __init__(self, *, config: Any) -> None:
        self.config = config
        self.current_stage: str | None = None
        self.calls = 0

    def run_once(self) -> None:
        self.calls += 1
        self.current_stage = "observer"
        raise RuntimeError(f"observer fail #{self.calls}")


def test_watch_trips_breaker_after_three_observer_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    artifacts_dir = tmp_path / "artifacts"
    state_db = tmp_path / "state.db"

    monkeypatch.setenv("PHOENIX_BASE_URL", "http://localhost:6006")
    monkeypatch.setenv("GOOGLE_API_KEY", "AIzaTEST")
    monkeypatch.setenv("NENGOK_ARTIFACTS_DIR", str(artifacts_dir))
    monkeypatch.setenv("NENGOK_STATE_DB", str(state_db))
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)

    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    def fake_open_breaker_pause(*, breaker: Any, config: Any, write_incident: Any) -> None:
        write_incident(
            artifacts_dir=config.artifacts_dir,
            filename="circuit-breaker.md",
            title="Circuit breaker tripped",
            body=f"stage={breaker.open_stage}",
        )
        breaker.close()
        raise KeyboardInterrupt

    monkeypatch.setattr("time.sleep", fake_sleep)
    monkeypatch.setattr(cli_module, "_open_breaker_pause", fake_open_breaker_pause)

    orchestrators: list[_AlwaysFailsOrchestrator] = []

    def fake_orchestrator(*, config: Any) -> _AlwaysFailsOrchestrator:
        orch = _AlwaysFailsOrchestrator(config=config)
        orchestrators.append(orch)
        return orch

    monkeypatch.setattr("nengok.core.orchestrator.Orchestrator", fake_orchestrator)

    runner = CliRunner()
    result = runner.invoke(cli_module.app, ["watch", "--interval", "0"])

    assert result.exit_code in (0, 1, 130)
    assert len(orchestrators) == 1
    assert orchestrators[0].calls == 3

    incidents = list((artifacts_dir / "incidents").rglob("circuit-breaker.md"))
    assert incidents, "expected a circuit-breaker incident artifact"
    assert "observer" in incidents[0].read_text(encoding="utf-8")
