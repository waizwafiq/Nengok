"""
ADK-defined agents.

This package is the single home for agents built on the Google Agent
Development Kit, so future Agent Builder work has somewhere obvious to
land without touching the deterministic ``nengok/core/`` tree. Today it
holds one agent: the triage gate that decides whether a cycle is worth
waking the full pipeline for.
"""

from nengok.agents.triage import (
    TriageAgent,
    TriageVerdict,
    adk_available,
    run_triage,
    triage_disabled_reason,
)

__all__ = [
    "TriageAgent",
    "TriageVerdict",
    "adk_available",
    "run_triage",
    "triage_disabled_reason",
]
