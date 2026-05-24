"""
Stage 2 of the loop: filter sampled spans down to those that look wrong.

Anomaly detection is intentionally rule-based and conservative. Spans
that pass this filter are still re-checked at the deduplication stage
against the state store, so it is safe to be permissive here.
"""

from __future__ import annotations

from dataclasses import dataclass

from nengok.core.types import AnomalousSpan, AnomalySignal, TraceSpan
from nengok.utils.logging import get_logger

logger = get_logger(__name__)

LATENCY_P95_MS = 5_000.0
LOW_EVAL_SCORE = 0.5


@dataclass
class AnomalyFilter:
    """Pure function dressed as a class for testability."""

    latency_threshold_ms: float = LATENCY_P95_MS
    low_eval_score: float = LOW_EVAL_SCORE

    def filter(self, spans: list[TraceSpan]) -> list[AnomalousSpan]:
        out: list[AnomalousSpan] = []
        for span in spans:
            signals = list(self._signals_for(span))
            if signals:
                out.append(AnomalousSpan(span=span, signals=signals))
        return out

    def _signals_for(self, span: TraceSpan):
        if span.status_code and span.status_code.upper().startswith("ERROR"):
            yield AnomalySignal.ERROR_STATUS

        if span.latency_ms is not None and span.latency_ms > self.latency_threshold_ms:
            yield AnomalySignal.HIGH_LATENCY

        for label, value in span.annotations.items():
            if isinstance(value, dict) and isinstance(value.get("score"), (int, float)):
                if value["score"] < self.low_eval_score:
                    yield AnomalySignal.LOW_EVAL_SCORE
                    break
            elif isinstance(value, (int, float)) and value < self.low_eval_score:
                yield AnomalySignal.LOW_EVAL_SCORE
                break

        if span.span_kind == "TOOL" and span.status_code and "error" in span.status_code.lower():
            yield AnomalySignal.TOOL_FAILURE

        if span.output_value is None or span.output_value.strip() == "":
            yield AnomalySignal.MISSING_OUTPUT_FIELD
