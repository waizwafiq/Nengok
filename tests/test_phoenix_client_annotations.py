"""`PhoenixWrapper` stitches span annotations onto the spans it returns.

These cover the integration that ``test_anomaly_filter.py`` cannot: the
filter is fed annotations from a dict, but nothing verified the wrapper
actually pulls them off the separate ``get_span_annotations`` endpoint and
attaches them under each annotation name. That merge is exactly what was
dead before this change, so it gets its own test.
"""

from __future__ import annotations

from typing import Any

import pytest

from nengok.config import NengokConfig
from nengok.errors import PhoenixTimeoutError
from nengok.phoenix.client import PhoenixWrapper


class _FakeSpans:
    def __init__(
        self,
        *,
        spans: list[dict[str, Any]],
        annotations: list[dict[str, Any]] | Exception,
    ) -> None:
        self._spans = spans
        self._annotations = annotations
        self.get_spans_calls: list[dict[str, Any]] = []
        self.annotation_calls: list[dict[str, Any]] = []

    def get_spans(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.get_spans_calls.append(kwargs)
        return self._spans

    def get_span_annotations(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.annotation_calls.append(kwargs)
        if isinstance(self._annotations, Exception):
            raise self._annotations
        return self._annotations


class _FakeClient:
    def __init__(self, spans: _FakeSpans) -> None:
        self.spans = spans


def _wrapper(config: NengokConfig, spans: _FakeSpans) -> PhoenixWrapper:
    wrapper = PhoenixWrapper(config)
    wrapper._client = _FakeClient(spans)
    return wrapper


def test_annotation_score_is_attached_to_the_span(tmp_config: NengokConfig) -> None:
    spans = _FakeSpans(
        spans=[{"span_id": "s1", "trace_id": "t1", "name": "agent", "output_value": "ok"}],
        annotations=[{"span_id": "s1", "name": "correctness", "result": {"score": 0.1}}],
    )
    wrapper = _wrapper(tmp_config, spans)

    out = wrapper.get_spans(project_identifier="travel-planner-agent", limit=10)

    assert len(out) == 1
    assert out[0].annotations["correctness"]["score"] == 0.1


def test_plain_scalar_result_is_wrapped_as_a_score(tmp_config: NengokConfig) -> None:
    spans = _FakeSpans(
        spans=[{"span_id": "s1", "trace_id": "t1", "name": "agent"}],
        annotations=[{"span_id": "s1", "name": "helpfulness", "result": 0.2}],
    )
    wrapper = _wrapper(tmp_config, spans)

    out = wrapper.get_spans(project_identifier="p", limit=10)

    assert out[0].annotations["helpfulness"] == {"score": 0.2}


def test_annotation_limit_is_sized_to_the_batch(tmp_config: NengokConfig) -> None:
    spans = _FakeSpans(
        spans=[
            {"span_id": "s1", "trace_id": "t1", "name": "agent"},
            {"span_id": "s2", "trace_id": "t2", "name": "agent"},
        ],
        annotations=[],
    )
    wrapper = _wrapper(tmp_config, spans)

    wrapper.get_spans(project_identifier="p", limit=10)

    assert spans.annotation_calls[0]["limit"] == 2 * 8


def test_missing_annotations_endpoint_falls_back_to_bare_spans(tmp_config: NengokConfig) -> None:
    spans = _FakeSpans(
        spans=[{"span_id": "s1", "trace_id": "t1", "name": "agent"}],
        annotations=RuntimeError("no such endpoint"),
    )
    wrapper = _wrapper(tmp_config, spans)

    out = wrapper.get_spans(project_identifier="p", limit=10)

    assert len(out) == 1
    assert out[0].annotations == {}


def test_annotation_timeout_escalates(tmp_config: NengokConfig) -> None:
    spans = _FakeSpans(
        spans=[{"span_id": "s1", "trace_id": "t1", "name": "agent"}],
        annotations=PhoenixTimeoutError(
            "boom",
            method="spans.get_span_annotations",
            timeout_seconds=0.05,
            observed_seconds=0.1,
        ),
    )
    wrapper = _wrapper(tmp_config, spans)

    with pytest.raises(PhoenixTimeoutError) as excinfo:
        wrapper.get_spans(project_identifier="p", limit=10)

    assert excinfo.value.method == "spans.get_span_annotations"


def test_get_spans_by_ids_skips_the_annotation_roundtrip(tmp_config: NengokConfig) -> None:
    spans = _FakeSpans(
        spans=[{"span_id": "s1", "trace_id": "t1", "name": "agent"}],
        annotations=[{"span_id": "s1", "name": "correctness", "result": {"score": 0.1}}],
    )
    wrapper = _wrapper(tmp_config, spans)

    out = wrapper.get_spans_by_ids(project_identifier="p", span_ids=["s1"])

    assert [s.span_id for s in out] == ["s1"]
    assert spans.annotation_calls == []
    assert out[0].annotations == {}
