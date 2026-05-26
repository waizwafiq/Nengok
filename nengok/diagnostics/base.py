"""
Shared types for `nengok doctor` probes.

A probe is a callable that inspects one piece of the install (config,
Phoenix, Gemini, etc.) and returns a `ProbeResult`. The result carries
a status, a short human-readable detail, and an optional fix hint so
the CLI can render a copy-paste recovery step on failure.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from nengok.config import NengokConfig


class ProbeStatus(str, Enum):
    """Outcome of a single probe. Doctor exits 1 when any FAIL is present."""

    OK = "ok"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of a single doctor probe."""

    name: str
    status: ProbeStatus
    detail: str
    fix_hint: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == ProbeStatus.OK

    @property
    def failed(self) -> bool:
        return self.status == ProbeStatus.FAIL

    @property
    def warned(self) -> bool:
        return self.status == ProbeStatus.WARN

    def to_dict(self) -> dict[str, str | None]:
        return {
            "name": self.name,
            "status": self.status.value,
            "detail": self.detail,
            "fix_hint": self.fix_hint,
        }


Probe = Callable[[NengokConfig], ProbeResult]
