"""
Protocol-conformant runner for the bundled Travel Planner demo.

Wraps :func:`sample_agent.agent.build_itinerary` behind the
:class:`~nengok.runners.protocol.AgentRunner` contract so the orchestrator
loads the demo through the same loader path a third-party agent uses.
"""

from __future__ import annotations

from typing import Any


class SampleAgentRunner:
    """Travel Planner runner wrapping ``build_itinerary``."""

    @property
    def name(self) -> str:
        return "travel-planner"

    def run(self, agent_input: dict[str, Any], prompt: str) -> dict[str, Any]:
        from sample_agent.agent import build_itinerary

        query = str(agent_input.get("query", ""))
        return build_itinerary(query, prompt=prompt)
