"""Unit tests for ``nengok.utils.tracing``."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from nengok.utils import tracing


class _RecordingSpan:
    def __init__(self) -> None:
        self.attributes: dict[str, Any] = {}

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value


def test_set_attributes_passes_primitives_unchanged() -> None:
    span = _RecordingSpan()
    tracing.set_attributes(
        span,
        {
            "str": "ok",
            "int": 7,
            "float": 0.5,
            "bool": True,
        },
    )
    assert span.attributes == {"str": "ok", "int": 7, "float": 0.5, "bool": True}


def test_set_attributes_stringifies_mappings_and_heterogeneous_lists() -> None:
    span = _RecordingSpan()
    tracing.set_attributes(
        span,
        {
            "dict": {"a": 1},
            "mixed_list": ["x", 1],
            "nested": [["a", "b"]],
        },
    )
    assert span.attributes["dict"] == repr({"a": 1})
    assert span.attributes["mixed_list"] == repr(["x", 1])
    assert span.attributes["nested"] == repr([["a", "b"]])


def test_set_attributes_preserves_homogeneous_lists() -> None:
    span = _RecordingSpan()
    tracing.set_attributes(span, {"counts": [1, 2, 3], "tags": ["a", "b"]})
    assert span.attributes == {"counts": [1, 2, 3], "tags": ["a", "b"]}


def test_set_attributes_passes_empty_list_unchanged() -> None:
    span = _RecordingSpan()
    tracing.set_attributes(span, {"empty": []})
    assert span.attributes == {"empty": []}


def test_set_attributes_coerces_none_to_empty_string() -> None:
    span = _RecordingSpan()
    tracing.set_attributes(span, {"maybe": None})
    assert span.attributes == {"maybe": ""}


def test_set_attributes_is_safe_on_null_span() -> None:
    tracing.set_attributes(None, {"x": 1})


def test_set_attributes_ignores_objects_without_setter() -> None:
    class _NoSetter:
        pass

    tracing.set_attributes(_NoSetter(), {"x": 1})


def test_null_tracer_yields_span_supporting_attribute_methods() -> None:
    tracer = tracing._NULL_TRACER
    with tracer.start_as_current_span("anything") as span:
        span.set_attribute("k", "v")
        span.set_attributes({"k": "v"})
        span.set_status("ok")
        span.record_exception(RuntimeError("ignored"))


def test_get_tracer_returns_null_when_opentelemetry_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved = sys.modules.pop("opentelemetry", None)
    monkeypatch.setitem(sys.modules, "opentelemetry", None)
    try:
        tracer = tracing.get_tracer("nengok-test")
        assert tracer is tracing._NULL_TRACER
    finally:
        if saved is not None:
            sys.modules["opentelemetry"] = saved
        else:
            sys.modules.pop("opentelemetry", None)


def test_get_tracer_returns_opentelemetry_tracer_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    def fake_get_tracer(name: str) -> str:
        captured["name"] = name
        return "real-tracer"

    fake_trace = types.SimpleNamespace(get_tracer=fake_get_tracer)
    fake_otel = types.ModuleType("opentelemetry")
    fake_otel.trace = fake_trace
    monkeypatch.setitem(sys.modules, "opentelemetry", fake_otel)
    monkeypatch.setitem(sys.modules, "opentelemetry.trace", fake_trace)

    tracer = tracing.get_tracer("nengok-test")
    assert tracer == "real-tracer"
    assert captured["name"] == "nengok-test"


def test_register_meta_tracer_returns_none_when_phoenix_otel_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "phoenix.otel", None)
    result = tracing.register_meta_tracer()
    assert result is None


def test_register_meta_tracer_invokes_phoenix_register_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_register(*, project_name: str, auto_instrument: bool) -> str:
        captured["project_name"] = project_name
        captured["auto_instrument"] = auto_instrument
        return "tracer-provider"

    fake_module = types.ModuleType("phoenix.otel")
    fake_module.register = fake_register  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "phoenix.otel", fake_module)

    result = tracing.register_meta_tracer(project_name="custom-meta")
    assert result == "tracer-provider"
    assert captured == {"project_name": "custom-meta", "auto_instrument": True}


def test_register_meta_tracer_swallows_runtime_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(**kwargs: Any) -> Any:
        del kwargs
        raise RuntimeError("phoenix offline")

    fake_module = types.ModuleType("phoenix.otel")
    fake_module.register = boom  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "phoenix.otel", fake_module)

    assert tracing.register_meta_tracer() is None
