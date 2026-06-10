"""
`PhoenixWrapper.get_spans` translates raw httpx failures into typed errors.

Before this coverage, a clean Phoenix instance (configured project never
created) surfaced as an `httpx.HTTPStatusError` traceback from `nengok run`
instead of the `PhoenixProjectNotFoundError` hint the CLI knows how to
render.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from nengok.config import NengokConfig
from nengok.errors import PhoenixConnectionError, PhoenixProjectNotFoundError
from nengok.phoenix.client import PhoenixWrapper


class _RaisingSpans:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def get_spans(self, **_kwargs: Any) -> list[dict[str, Any]]:
        raise self._exc


class _FakeClient:
    def __init__(self, spans: _RaisingSpans) -> None:
        self.spans = spans


def _wrapper(config: NengokConfig, exc: Exception) -> PhoenixWrapper:
    wrapper = PhoenixWrapper(config)
    wrapper._client = _FakeClient(_RaisingSpans(exc))
    return wrapper


def _status_error(status_code: int) -> httpx.HTTPStatusError:
    url = "http://localhost:6006/v1/projects/travel-planner-agent/spans"
    request = httpx.Request("GET", url)
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(f"{status_code}", request=request, response=response)


def test_missing_project_raises_typed_not_found(tmp_config: NengokConfig) -> None:
    wrapper = _wrapper(tmp_config, _status_error(404))

    with pytest.raises(PhoenixProjectNotFoundError) as excinfo:
        wrapper.get_spans(project_identifier="travel-planner-agent", limit=10)

    assert excinfo.value.project_identifier == "travel-planner-agent"
    assert "sample_agent.seed" in str(excinfo.value)


def test_non_404_status_errors_propagate_unchanged(tmp_config: NengokConfig) -> None:
    wrapper = _wrapper(tmp_config, _status_error(500))

    with pytest.raises(httpx.HTTPStatusError):
        wrapper.get_spans(project_identifier="travel-planner-agent", limit=10)


def test_transport_failure_raises_typed_connection_error(tmp_config: NengokConfig) -> None:
    wrapper = _wrapper(tmp_config, httpx.ConnectError("connection refused"))

    with pytest.raises(PhoenixConnectionError) as excinfo:
        wrapper.get_spans(project_identifier="travel-planner-agent", limit=10)

    assert "http://localhost:6006" in str(excinfo.value)
