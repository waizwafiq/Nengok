"""
Stable agent-runner interface for Phoenix experiments.

A runner is any callable that turns ``(input_dict, prompt) -> output_dict``.
Phoenix's `run_experiment` calls it once per dataset row with the
candidate prompt threaded through, then hands the output dict to the
evaluator stack. Keeping the interface this narrow lets production
users register their own monitored agent without touching the Nengok
core loop.

The registry maps a project identifier (the same value that flows
through `NengokConfig.project_identifier`) to a runner. `nengok run`
looks the runner up by project name when wiring an experiment.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

AgentRunner = Callable[[dict[str, Any], str], dict[str, Any]]

SAMPLE_AGENT_PROJECT = "travel-planner-agent"

_RUNNERS: dict[str, AgentRunner] = {}


def register_runner(project_identifier: str, runner: AgentRunner) -> None:
    """Attach a runner to a project identifier, replacing any prior entry."""
    _RUNNERS[project_identifier] = runner


def get_runner(project_identifier: str) -> AgentRunner | None:
    """Return the runner registered for a project, or None if unregistered."""
    return _RUNNERS.get(project_identifier)


def sample_agent_runner(input_row: dict[str, Any], prompt: str) -> dict[str, Any]:
    """
    Runner for the bundled Travel Planner demo.

    The dataset's ``input`` mapping is expected to carry a ``query`` key;
    the prompt is injected into ``build_itinerary`` instead of being
    read from disk so the experiment can A/B baseline against a fix.
    """
    from sample_agent.agent import build_itinerary

    query = str(input_row.get("query", ""))
    return build_itinerary(query, prompt=prompt)


register_runner(SAMPLE_AGENT_PROJECT, sample_agent_runner)
