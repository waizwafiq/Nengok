"""
Agent runners for Phoenix experiments.

The Phoenix experiment loop needs a callable that takes a dataset row's
input plus a candidate prompt and returns whatever shape the evaluators
read. The :class:`AgentRunner` Protocol is the formal contract; real
users plug in their own runner class. The bundled Travel Planner runner
is what the demo cycle uses out of the box.
"""

from nengok.runners.agent_runner import (
    SAMPLE_AGENT_PROJECT,
    get_runner,
    register_runner,
    sample_agent_runner,
)
from nengok.runners.protocol import AgentRunner
from nengok.runners.sample_agent_runner import SampleAgentRunner

__all__ = [
    "SAMPLE_AGENT_PROJECT",
    "AgentRunner",
    "SampleAgentRunner",
    "get_runner",
    "register_runner",
    "sample_agent_runner",
]
