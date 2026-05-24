"""
Stage 1 of the loop: pull a window of recent spans from Phoenix.

This wraps `PhoenixWrapper.get_spans` so the orchestrator never imports
the Phoenix SDK directly. That keeps the orchestrator unit-testable
with an in-memory fake.
"""

from __future__ import annotations

from dataclasses import dataclass

from nengok.config import NengokConfig
from nengok.core.types import TraceSpan
from nengok.phoenix.client import PhoenixWrapper
from nengok.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class SpanSampler:
    phoenix: PhoenixWrapper
    config: NengokConfig

    def sample(self) -> list[TraceSpan]:
        return self.phoenix.get_spans(
            project_identifier=self.config.project_identifier,
            limit=self.config.span_limit,
        )
