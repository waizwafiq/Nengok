"""The narrow contract every Nengok notifier must satisfy.

Mirrors the AgentRunner protocol: a small, runtime-checkable interface
so the loader can verify compliance before any dispatch fires and so
third-party notifiers can be loaded from dotted-path specs.

``name`` is the registry key. It must be stable across releases because
it is part of the deduplication key in ``nengok_notifications``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from nengok.notifiers.events import EscalationEvent, FixProposedEvent


@dataclass
class NotifierResult:
    success: bool
    notifier_state: dict | None = field(default=None)
    error: str | None = field(default=None)


@runtime_checkable
class Notifier(Protocol):
    """The narrow contract a Nengok notifier must satisfy."""

    @property
    def name(self) -> str: ...

    def notify_fix_proposed(self, event: FixProposedEvent, *, dry_run: bool) -> NotifierResult: ...

    def notify_escalation(self, event: EscalationEvent, *, dry_run: bool) -> NotifierResult: ...
