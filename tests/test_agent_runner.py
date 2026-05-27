"""Runner registry tests."""

from __future__ import annotations

from typing import Any

from nengok.runners import AgentRunner, SampleAgentRunner
from nengok.runners.agent_runner import (
    SAMPLE_AGENT_PROJECT,
    get_runner,
    register_runner,
)


def test_sample_agent_runner_is_preregistered() -> None:
    runner = get_runner(SAMPLE_AGENT_PROJECT)
    assert runner is not None
    assert isinstance(runner, AgentRunner)
    assert isinstance(runner, SampleAgentRunner)


def test_unknown_project_returns_none() -> None:
    assert get_runner("never-registered-agent") is None


def test_register_runner_accepts_protocol_instance() -> None:
    class StubRunner:
        @property
        def name(self) -> str:
            return "stub"

        def run(self, agent_input: dict[str, Any], _prompt: str) -> dict[str, Any]:
            return {"echo": agent_input.get("query", "")}

    stub = StubRunner()
    register_runner("test-agent-protocol", stub)
    bound = get_runner("test-agent-protocol")
    assert bound is stub
    assert bound.run({"query": "x"}, "p") == {"echo": "x"}


def test_register_runner_wraps_legacy_callable() -> None:
    def fake_runner(_row: dict[str, Any], _prompt: str) -> dict[str, Any]:
        return {"echo": "ok"}

    register_runner("test-agent-callable", fake_runner)
    bound = get_runner("test-agent-callable")
    assert bound is not None
    assert isinstance(bound, AgentRunner)
    assert bound.name == "test-agent-callable"
    assert bound.run({"query": "x"}, "p") == {"echo": "ok"}
