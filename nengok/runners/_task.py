"""
Adapter between the Nengok runner protocol and Phoenix's experiment task signature.

Phoenix's ``run_experiment`` invokes the task callable with one
positional argument: the dataset example as a Mapping. The Nengok
runner protocol takes ``(agent_input, prompt)``. Keeping the bridge
here means :class:`~nengok.phoenix.client.PhoenixWrapper` only knows
about Phoenix wiring and stays out of agent-invocation concerns.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from nengok.runners.protocol import AgentRunner


def build_task(runner: AgentRunner, prompt: str) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    """Wrap an :class:`AgentRunner` in the signature Phoenix's run_experiment calls."""

    def task(example: Mapping[str, Any]) -> dict[str, Any]:
        raw_input = example.get("input") or {}
        input_row: dict[str, Any] = (
            dict(raw_input) if isinstance(raw_input, Mapping) else {"value": raw_input}
        )
        return runner.run(input_row, prompt)

    return task
