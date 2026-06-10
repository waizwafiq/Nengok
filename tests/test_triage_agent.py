"""
Unit coverage for `run_triage` against a fake ADK runner.

The fakes mimic the surface `_run_triage_async` touches (session
service, `run_async` event stream, `close`), so these tests run on the
minimal-deps CI job without google-adk installed. The real ADK wiring
in `_build_runner` is exercised by the full-extras job's import check
and by the live loop.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
from typing import Any

import pytest
from pydantic import ValidationError

from nengok.agents.triage import (
    TriageVerdict,
    adk_available,
    run_triage,
    triage_disabled_reason,
)
from nengok.config import NengokConfig
from nengok.errors import TriageError
from nengok.phoenix.mcp import MCPError

VALID_VERDICT = json.dumps(
    {
        "investigate": True,
        "project": "travel-planner-agent",
        "window_minutes": 15,
        "reason": "error burst in flights tool",
        "signals": ["error_status"],
    }
)

INVALID_VERDICT = json.dumps({"investigate": True, "unexpected_field": "boom"})


def _config(**overrides: Any) -> NengokConfig:
    defaults: dict[str, Any] = {
        "phoenix_base_url": "http://localhost:6006",
        "google_api_key": "AIzaTEST",
        "project_identifier": "travel-planner-agent",
        "triage_timeout_seconds": 5.0,
    }
    defaults.update(overrides)
    return NengokConfig(**defaults)


class _FakePart:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeContent:
    def __init__(self, text: str) -> None:
        self.parts = [_FakePart(text)]


class _FakeEvent:
    def __init__(self, text: str, *, final: bool = True) -> None:
        self.content = _FakeContent(text)
        self._final = final

    def is_final_response(self) -> bool:
        return self._final


class _FakeSession:
    id = "session-1"


class _FakeSessionService:
    async def create_session(self, **kwargs: Any) -> _FakeSession:
        del kwargs
        return _FakeSession()


class _FakeRunner:
    def __init__(self, events: list[_FakeEvent], *, sleep_seconds: float = 0.0) -> None:
        self._events = events
        self._sleep_seconds = sleep_seconds
        self.session_service = _FakeSessionService()
        self.closed = False

    async def run_async(self, **kwargs: Any) -> Any:
        del kwargs
        if self._sleep_seconds:
            await asyncio.sleep(self._sleep_seconds)
        for event in self._events:
            yield event

    async def close(self) -> None:
        self.closed = True


def test_happy_path_returns_parsed_verdict() -> None:
    runner = _FakeRunner([_FakeEvent(VALID_VERDICT)])

    verdict = run_triage(_config(), runner_factory=lambda _cfg: runner)

    assert verdict == TriageVerdict(
        investigate=True,
        project="travel-planner-agent",
        window_minutes=15,
        reason="error burst in flights tool",
        signals=["error_status"],
    )
    assert runner.closed


def test_markdown_fenced_verdict_is_parsed() -> None:
    fenced = f"```json\n{VALID_VERDICT}\n```"
    runner = _FakeRunner([_FakeEvent(fenced)])

    verdict = run_triage(_config(), runner_factory=lambda _cfg: runner)

    assert verdict.investigate is True


def test_non_final_events_are_ignored() -> None:
    events = [
        _FakeEvent("thinking...", final=False),
        _FakeEvent(VALID_VERDICT),
    ]
    runner = _FakeRunner(events)

    verdict = run_triage(_config(), runner_factory=lambda _cfg: runner)

    assert verdict.window_minutes == 15


def test_schema_violation_retries_once_then_succeeds() -> None:
    runners = [
        _FakeRunner([_FakeEvent(INVALID_VERDICT)]),
        _FakeRunner([_FakeEvent(VALID_VERDICT)]),
    ]
    calls = {"count": 0}

    def factory(_cfg: NengokConfig) -> _FakeRunner:
        runner = runners[calls["count"]]
        calls["count"] += 1
        return runner

    verdict = run_triage(_config(), runner_factory=factory)

    assert calls["count"] == 2
    assert verdict.investigate is True
    assert all(runner.closed for runner in runners)


def test_persistent_schema_violation_raises_validation_error() -> None:
    calls = {"count": 0}

    def factory(_cfg: NengokConfig) -> _FakeRunner:
        calls["count"] += 1
        return _FakeRunner([_FakeEvent(INVALID_VERDICT)])

    with pytest.raises(ValidationError):
        run_triage(_config(), runner_factory=factory)

    assert calls["count"] == 2


def test_out_of_range_window_raises_validation_error() -> None:
    payload = json.dumps(
        {
            "investigate": True,
            "project": "p",
            "window_minutes": 9_999,
            "reason": "too wide",
            "signals": [],
        }
    )

    with pytest.raises(ValidationError):
        run_triage(_config(), runner_factory=lambda _cfg: _FakeRunner([_FakeEvent(payload)]))


def test_slow_runner_times_out() -> None:
    runner = _FakeRunner([_FakeEvent(VALID_VERDICT)], sleep_seconds=30.0)

    with pytest.raises(TimeoutError):
        run_triage(_config(triage_timeout_seconds=1.0), runner_factory=lambda _cfg: runner)


def test_mcp_unavailable_propagates() -> None:
    def factory(_cfg: NengokConfig) -> _FakeRunner:
        raise MCPError("npx exploded")

    with pytest.raises(MCPError):
        run_triage(_config(), runner_factory=factory)


def test_empty_event_stream_raises_triage_error() -> None:
    runner = _FakeRunner([])

    with pytest.raises(TriageError, match="without a final response"):
        run_triage(_config(), runner_factory=lambda _cfg: runner)


def test_unexpected_exception_is_wrapped_as_triage_error() -> None:
    def factory(_cfg: NengokConfig) -> _FakeRunner:
        raise RuntimeError("adk internals fell over")

    with pytest.raises(TriageError, match="RuntimeError"):
        run_triage(_config(), runner_factory=factory)


def test_refuses_to_run_inside_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nengok.state.connection.in_transaction", lambda: True)

    with pytest.raises(RuntimeError, match="database transaction"):
        run_triage(_config(), runner_factory=lambda _cfg: _FakeRunner([_FakeEvent(VALID_VERDICT)]))


def test_disabled_reason_when_config_off() -> None:
    reason = triage_disabled_reason(_config(triage_enabled=False))
    assert reason is not None
    assert "triage_enabled" in reason


def test_disabled_reason_when_adk_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nengok.agents.triage.adk_available", lambda: False)

    reason = triage_disabled_reason(_config())

    assert reason is not None
    assert "nengok[adk]" in reason


def test_disabled_reason_when_npx_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nengok.agents.triage.adk_available", lambda: True)
    monkeypatch.setattr("nengok.agents.triage.shutil.which", lambda _cmd: None)

    reason = triage_disabled_reason(_config())

    assert reason is not None
    assert "PATH" in reason


def test_disabled_reason_none_when_runnable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nengok.agents.triage.adk_available", lambda: True)
    monkeypatch.setattr("nengok.agents.triage.shutil.which", lambda _cmd: "/usr/bin/npx")

    assert triage_disabled_reason(_config()) is None


def test_adk_available_never_raises() -> None:
    assert isinstance(adk_available(), bool)


def test_adk_available_false_when_google_namespace_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(name: str) -> None:
        raise ModuleNotFoundError("No module named 'google'")

    monkeypatch.setattr("importlib.util.find_spec", _raise)

    assert adk_available() is False


def test_adk_available_false_when_mcp_sdk_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    real_find_spec = importlib.util.find_spec

    def _no_mcp(name: str) -> object | None:
        if name == "mcp":
            return None
        return real_find_spec(name)

    monkeypatch.setattr("importlib.util.find_spec", _no_mcp)

    assert adk_available() is False


def test_redact_tool_payload_scrubs_nested_strings() -> None:
    from nengok.agents.triage import redact_tool_payload
    from nengok.core.observer.redactor import Redactor

    redactor = Redactor.from_config(_config())
    payload = {
        "content": [
            {
                "type": "text",
                "text": "contact user@example.com about key AIzaSyD1234567890abcdefghijklmnopqrstuvw",
            }
        ],
        "count": 3,
        "nested": {"note": "card 4111-1111-1111-1111"},
    }

    redacted = redact_tool_payload(payload, redactor)

    flat = json.dumps(redacted)
    assert "user@example.com" not in flat
    assert "4111-1111-1111-1111" not in flat
    assert redacted["count"] == 3
    assert redacted["content"][0]["type"] == "text"
