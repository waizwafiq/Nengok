"""Runtime conformance tests for the :class:`AgentRunner` protocol."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from nengok.runners import AgentRunner, SampleAgentRunner
from nengok.runners._task import build_task


def test_sample_runner_satisfies_protocol() -> None:
    assert isinstance(SampleAgentRunner(), AgentRunner)


def test_sample_runner_name_is_stable() -> None:
    assert SampleAgentRunner().name == "travel-planner"


def test_legacy_callable_does_not_satisfy_protocol() -> None:
    def bare_callable(_input: dict[str, Any], _prompt: str) -> dict[str, Any]:
        return {"ok": True}

    assert not isinstance(bare_callable, AgentRunner)


def test_build_task_invokes_runner_with_input_and_prompt() -> None:
    seen: list[tuple[dict[str, Any], str]] = []

    class StubRunner:
        @property
        def name(self) -> str:
            return "stub"

        def run(self, agent_input: dict[str, Any], prompt: str) -> dict[str, Any]:
            seen.append((agent_input, prompt))
            return {"echo": agent_input.get("query", "")}

    task = build_task(StubRunner(), "fix-candidate-prompt")
    result = task({"input": {"query": "what about Tokyo?"}})

    assert seen == [({"query": "what about Tokyo?"}, "fix-candidate-prompt")]
    assert result == {"echo": "what about Tokyo?"}


def test_build_task_wraps_non_mapping_input_under_value_key() -> None:
    captured: list[dict[str, Any]] = []

    class StubRunner:
        @property
        def name(self) -> str:
            return "stub"

        def run(self, agent_input: dict[str, Any], _prompt: str) -> dict[str, Any]:
            captured.append(agent_input)
            return {}

    task = build_task(StubRunner(), "p")
    task({"input": "bare-string-input"})

    assert captured == [{"value": "bare-string-input"}]


def test_build_task_handles_missing_input_key() -> None:
    class StubRunner:
        @property
        def name(self) -> str:
            return "stub"

        def run(self, agent_input: dict[str, Any], _prompt: str) -> dict[str, Any]:
            return {"got": dict(agent_input)}

    task = build_task(StubRunner(), "p")
    example: Mapping[str, Any] = {}

    assert task(example) == {"got": {}}
