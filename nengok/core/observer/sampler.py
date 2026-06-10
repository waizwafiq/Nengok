"""
Stage 1 of the loop: pull a window of recent spans from Phoenix.

This wraps `PhoenixWrapper.get_spans` so the orchestrator never imports
the Phoenix SDK directly. That keeps the orchestrator unit-testable
with an in-memory fake.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from nengok.config import NengokConfig
from nengok.core.types import TraceSpan
from nengok.phoenix.client import PhoenixWrapper
from nengok.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class SpanSampler:
    phoenix: PhoenixWrapper
    config: NengokConfig

    def sample(
        self,
        *,
        project_identifier: str | None = None,
        window_minutes: int | None = None,
    ) -> list[TraceSpan]:
        """
        Pull recent spans, optionally narrowed by the triage verdict.

        The triage gate at the head of the cycle may point the Observer
        at a different project and a tighter time window than the
        configured defaults.
        """
        start_time = None
        if window_minutes is not None:
            start_time = datetime.now(UTC) - timedelta(minutes=window_minutes)
        return self.phoenix.get_spans(
            project_identifier=project_identifier or self.config.project_identifier,
            limit=self.config.span_limit,
            start_time=start_time,
        )
