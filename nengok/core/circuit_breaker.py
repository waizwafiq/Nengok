"""
Per-stage circuit breaker for the `nengok watch` loop.

If the same stage (observer, diagnoser, fixer, verifier) fails N cycles
in a row, the breaker opens and the watch loop sleeps for a back-off
window before retrying. Each open writes an incident artifact so the
operator can investigate without grepping log files.
"""

from __future__ import annotations

import traceback
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta


@dataclass
class StageFailure:
    """One captured stage exception."""

    stage: str
    error_class: str
    message: str
    traceback: str
    recorded_at: datetime


@dataclass
class CircuitBreaker:
    """
    Track consecutive failures per stage; open after `threshold` in a row.

    The orchestrator stamps the current stage onto each cycle so the
    watch loop can call `record_failure(stage, exc)` on the right
    counter. Successful cycles reset every counter; success in one
    stage does not clear a different stage that has been failing.
    """

    threshold: int = 3
    backoff_seconds: int = 900
    _counts: dict[str, int] = field(default_factory=dict)
    _recent_failures: deque[StageFailure] = field(default_factory=lambda: deque(maxlen=3))
    _opened_at: datetime | None = field(default=None)
    _open_stage: str | None = field(default=None)

    def record_success(self, stage: str) -> None:
        del stage
        self._counts.clear()
        self._opened_at = None
        self._open_stage = None

    def record_failure(self, stage: str, exc: BaseException) -> bool:
        count = self._counts.get(stage, 0) + 1
        self._counts[stage] = count
        failure = StageFailure(
            stage=stage,
            error_class=type(exc).__name__,
            message=str(exc),
            traceback="".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            recorded_at=datetime.now(UTC),
        )
        self._recent_failures.append(failure)
        if count >= self.threshold:
            self._opened_at = datetime.now(UTC)
            self._open_stage = stage
            return True
        return False

    @property
    def is_open(self) -> bool:
        return self._opened_at is not None

    @property
    def open_stage(self) -> str | None:
        return self._open_stage

    def time_until_close(self) -> timedelta:
        if self._opened_at is None:
            return timedelta(0)
        elapsed = datetime.now(UTC) - self._opened_at
        remaining = timedelta(seconds=self.backoff_seconds) - elapsed
        return max(remaining, timedelta(0))

    def close(self) -> None:
        self._opened_at = None
        self._open_stage = None
        self._counts.clear()

    def recent_failures(self) -> Iterable[StageFailure]:
        return list(self._recent_failures)
