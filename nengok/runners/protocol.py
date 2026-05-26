"""
The formal contract every monitored agent must satisfy.

A runner is the bridge between a Phoenix dataset row and the agent's
own invocation. `agent_input` is one row from a Phoenix dataset (the
mapping under ``example["input"]``). `prompt` is the candidate prompt
being evaluated for this experiment, threaded in so the verifier can
A/B a fix candidate against the on-disk baseline without touching the
agent's bundled prompt file. The return value is whatever shape the
project's evaluator stack reads.

``name`` namespaces artifacts and traces. Pick a short, file-safe
identifier (the value flows into ``artifacts/<name>/<cluster>/`` and
into ``nengok.cluster.runner`` span attributes), and keep it stable
across releases of the runner so historical cycles still link up.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AgentRunner(Protocol):
    """The narrow contract a Nengok-monitored agent must satisfy."""

    @property
    def name(self) -> str: ...

    def run(self, agent_input: dict[str, Any], prompt: str) -> dict[str, Any]: ...
