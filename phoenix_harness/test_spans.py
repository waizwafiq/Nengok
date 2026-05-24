"""Smoke test: we can fetch and normalize at least one real span."""

from __future__ import annotations

from nengok.config import NengokConfig
from nengok.phoenix.client import PhoenixWrapper


def test_get_spans_returns_normalized_traces(phoenix_config: NengokConfig) -> None:
    wrapper = PhoenixWrapper(phoenix_config)
    spans = wrapper.get_spans(project_identifier=phoenix_config.project_identifier, limit=10)
    assert isinstance(spans, list)
    for span in spans:
        assert span.span_id
        assert span.trace_id
