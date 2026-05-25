"""
Agent runners for Phoenix experiments.

The Phoenix experiment loop needs a callable that takes a dataset row's
input plus a candidate prompt and returns whatever shape the evaluators
read. Real users plug in their own runner; the bundled sample-agent
runner is what the Travel Planner demo uses.
"""

from nengok.runners.agent_runner import (
    AgentRunner,
    get_runner,
    register_runner,
    sample_agent_runner,
)

__all__ = [
    "AgentRunner",
    "get_runner",
    "register_runner",
    "sample_agent_runner",
]
