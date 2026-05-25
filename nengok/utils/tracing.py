"""
Self-instrumentation for the Nengok meta-agent.

Section 5.4 of the proposal asks for the loop itself to be traced in
Phoenix so a developer running ``nengok run`` can inspect every
clustering decision, hypothesis, and verifier outcome as a span.

``arize-phoenix-otel`` is an optional extra. When it is missing the
helpers below return a no-op tracer so the SDK still works on a
barebones install.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from nengok.utils.logging import get_logger

logger = get_logger(__name__)

META_PROJECT_NAME = "nengok-meta-agent"
TRACER_NAME = "nengok"


class _NullSpan:
    """A span stand-in used when OpenTelemetry is not installed."""

    def set_attribute(self, key: str, value: Any) -> None:
        del key, value

    def set_attributes(self, attributes: Mapping[str, Any]) -> None:
        del attributes

    def set_status(self, status: Any) -> None:
        del status

    def record_exception(self, exc: BaseException) -> None:
        del exc


class _NullTracer:
    """Tracer fallback that yields a ``_NullSpan`` from every span call."""

    @contextmanager
    def start_as_current_span(self, name: str, **kwargs: Any) -> Iterator[_NullSpan]:
        del name, kwargs
        yield _NullSpan()


_NULL_TRACER = _NullTracer()


def register_meta_tracer(*, project_name: str = META_PROJECT_NAME) -> Any | None:
    """
    Register the Nengok meta-tracer with Phoenix.

    Returns the tracer provider when the optional ``arize-phoenix-otel``
    extra is installed, otherwise None. Callers do not need to branch on
    the return value, since ``get_tracer`` falls back to a no-op tracer
    when registration was skipped.
    """
    try:
        from phoenix.otel import register
    except ImportError:
        logger.debug("arize-phoenix-otel not installed, meta-tracing disabled.")
        return None

    try:
        return register(project_name=project_name, auto_instrument=True)
    except Exception:
        logger.warning(
            "Phoenix OTEL registration failed, continuing without meta-tracing.",
            exc_info=True,
        )
        return None


def get_tracer(name: str = TRACER_NAME) -> Any:
    """
    Return an OpenTelemetry tracer when available, otherwise a no-op.

    The no-op preserves the orchestrator's ``with tracer.start_as_current_span(...)``
    blocks so the rest of the loop does not have to branch on whether
    OTEL is installed.
    """
    try:
        from opentelemetry import trace
    except ImportError:
        return _NULL_TRACER
    return trace.get_tracer(name)


def set_attributes(span: Any, attributes: Mapping[str, Any]) -> None:
    """
    Apply attributes to an OpenTelemetry span, coercing non-primitive values.

    OpenTelemetry only accepts primitives and homogeneous sequences. Any
    mapping or heterogeneous sequence is stringified via ``repr`` so the
    call site can pass anything without pre-serializing.
    """
    if span is None:
        return
    setter = getattr(span, "set_attribute", None)
    if setter is None:
        return
    for key, value in attributes.items():
        setter(key, _coerce(value))


def _coerce(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, str | bool | int | float):
        return value
    if isinstance(value, Mapping):
        return repr(dict(value))
    if isinstance(value, list | tuple):
        seq = list(value)
        if not seq:
            return seq
        first_type = type(seq[0])
        if first_type in {str, bool, int, float} and all(type(item) is first_type for item in seq):
            return seq
        return repr(seq)
    return repr(value)
