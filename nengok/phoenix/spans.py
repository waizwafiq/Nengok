"""
Convert raw Phoenix span payloads into our normalized `TraceSpan` shape.

The Phoenix client returns a typed object today but we go through dicts
defensively so we are resilient to minor upstream shape changes during
the hackathon (Phoenix's client is still on a 0.x release line).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from nengok.core.types import TraceSpan


def normalize_span(raw: Any) -> TraceSpan:
    payload = _to_dict(raw)
    attributes = payload.get("attributes") or {}
    annotations = payload.get("annotations") or {}

    return TraceSpan(
        span_id=str(payload.get("span_id") or payload.get("context", {}).get("span_id", "")),
        trace_id=str(payload.get("trace_id") or payload.get("context", {}).get("trace_id", "")),
        name=str(payload.get("name", "")),
        span_kind=attributes.get("openinference.span.kind") or payload.get("span_kind"),
        session_id=attributes.get("session.id") or payload.get("session_id"),
        status_code=payload.get("status_code") or payload.get("status", {}).get("code"),
        latency_ms=_to_float(payload.get("latency_ms") or payload.get("duration_ms")),
        input_value=attributes.get("input.value") or payload.get("input_value"),
        output_value=attributes.get("output.value") or payload.get("output_value"),
        attributes=attributes,
        annotations=annotations,
        started_at=_to_datetime(payload.get("start_time") or payload.get("started_at")),
    )


def _to_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if hasattr(raw, "model_dump"):
        return raw.model_dump()
    if hasattr(raw, "__dict__"):
        return {k: v for k, v in vars(raw).items() if not k.startswith("_")}
    return {}


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None
