"""Runner registry tests."""

from __future__ import annotations

from typing import Any

from nengok.runners.agent_runner import (
    SAMPLE_AGENT_PROJECT,
    get_runner,
    register_runner,
)


def test_sample_agent_runner_is_preregistered() -> None:
    runner = get_runner(SAMPLE_AGENT_PROJECT)
    assert runner is not None
    assert callable(runner)


def test_unknown_project_returns_none() -> None:
    assert get_runner("never-registered-agent") is None


def test_register_runner_overrides_existing_entry() -> None:
    def fake_runner(_row: dict[str, Any], _prompt: str) -> dict[str, Any]:
        return {"echo": "ok"}

    register_runner("test-agent-runner", fake_runner)
    bound = get_runner("test-agent-runner")
    assert bound is fake_runner
    assert bound({"query": "x"}, "p") == {"echo": "ok"}
