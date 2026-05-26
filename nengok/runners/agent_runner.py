"""
Project-id to runner registry.

The runner is any object satisfying :class:`~nengok.runners.protocol.AgentRunner`.
Legacy callables of the form ``(input_row, prompt) -> output_row`` are
also accepted by :func:`register_runner`; they get adapted on the fly
so older bootstrap modules keep working while new code targets the
Protocol directly.

The orchestrator looks up the runner by project name when wiring an
experiment. Phase 8.2 adds a config-driven loader that constructs a
runner from a dotted path; this registry remains for users who prefer
imperative registration from their own bootstrap.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nengok.runners.protocol import AgentRunner
from nengok.runners.sample_agent_runner import SampleAgentRunner

LegacyRunner = Callable[[dict[str, Any], str], dict[str, Any]]

SAMPLE_AGENT_PROJECT = "travel-planner-agent"

_RUNNERS: dict[str, AgentRunner] = {}


class _CallableRunnerAdapter:
    """Adapt a bare ``(input_row, prompt) -> output_row`` callable to AgentRunner."""

    def __init__(self, name: str, fn: LegacyRunner) -> None:
        self._name = name
        self._fn = fn

    @property
    def name(self) -> str:
        return self._name

    def run(self, agent_input: dict[str, Any], prompt: str) -> dict[str, Any]:
        return self._fn(agent_input, prompt)


def register_runner(project_identifier: str, runner: AgentRunner | LegacyRunner) -> None:
    """
    Attach a runner to a project identifier, replacing any prior entry.

    Accepts either a Protocol-conformant runner instance or a legacy
    callable. Callables are wrapped in an adapter that exposes the
    project identifier as ``name``.
    """
    if isinstance(runner, AgentRunner):
        _RUNNERS[project_identifier] = runner
    elif callable(runner):
        _RUNNERS[project_identifier] = _CallableRunnerAdapter(project_identifier, runner)
    else:
        raise TypeError(f"register_runner expected an AgentRunner or callable, got {type(runner).__name__}.")


def get_runner(project_identifier: str) -> AgentRunner | None:
    """Return the runner registered for a project, or ``None`` if unregistered."""
    return _RUNNERS.get(project_identifier)


def sample_agent_runner(input_row: dict[str, Any], prompt: str) -> dict[str, Any]:
    """Legacy callable form of :class:`SampleAgentRunner` kept for bootstrap modules."""
    return SampleAgentRunner().run(input_row, prompt)


register_runner(SAMPLE_AGENT_PROJECT, SampleAgentRunner())
