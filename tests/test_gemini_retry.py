"""Retry, backoff, and timeout behavior for `call_gemini`."""

from __future__ import annotations

import time
from typing import Any

import pytest

genai_errors = pytest.importorskip(
    "google.genai.errors",
    reason="google-genai not installed; retry tests need the gemini extra.",
)

from nengok.utils.gemini import (
    GeminiAuthError,
    GeminiQuotaError,
    GeminiTimeoutError,
    InvalidGeminiModelError,
    RetryPolicy,
    call_gemini,
)


class _ScriptedModels:
    """Models stub that pops a scripted action per call."""

    def __init__(self, actions: list[Any], text: str = "ok") -> None:
        self._actions = list(actions)
        self._text = text
        self.calls = 0

    def generate_content(self, **kwargs: Any) -> Any:
        self.calls += 1
        if self._actions:
            action = self._actions.pop(0)
            if isinstance(action, Exception):
                raise action
            if callable(action):
                action()
        return _Response(self._text)


class _Response:
    def __init__(self, text: str) -> None:
        self.text = text


class _StubClient:
    def __init__(self, actions: list[Any], text: str = "ok") -> None:
        self.models = _ScriptedModels(actions, text=text)


def _quota_error() -> genai_errors.ClientError:
    return genai_errors.ClientError(
        429,
        {"error": {"code": 429, "message": "Quota exceeded", "status": "RESOURCE_EXHAUSTED"}},
    )


def _fast_policy(max_attempts: int = 3) -> RetryPolicy:
    return RetryPolicy(
        max_attempts=max_attempts,
        min_backoff_seconds=0.0,
        max_backoff_seconds=0.0,
        timeout_seconds=0.0,
    )


def test_retries_quota_then_succeeds() -> None:
    client = _StubClient(actions=[_quota_error(), _quota_error()], text="done")

    result = call_gemini(
        client,
        model="gemini-3.1-pro-preview",
        contents=[{"role": "user"}],
        retry_policy=_fast_policy(),
    )

    assert result == "done"
    assert client.models.calls == 3


def test_reraises_original_after_budget_exhausted() -> None:
    client = _StubClient(actions=[_quota_error(), _quota_error(), _quota_error()])

    with pytest.raises(GeminiQuotaError):
        call_gemini(
            client,
            model="m",
            contents=[],
            retry_policy=_fast_policy(max_attempts=3),
        )

    assert client.models.calls == 3


def test_no_retry_on_auth_failure() -> None:
    auth_error = genai_errors.ClientError(
        403,
        {"error": {"code": 403, "message": "Permission denied", "status": "PERMISSION_DENIED"}},
    )
    client = _StubClient(actions=[auth_error, auth_error, auth_error])

    with pytest.raises(GeminiAuthError):
        call_gemini(
            client,
            model="m",
            contents=[],
            retry_policy=_fast_policy(),
        )

    assert client.models.calls == 1


def test_no_retry_on_invalid_model() -> None:
    not_found = genai_errors.ClientError(
        404,
        {"error": {"code": 404, "message": "model bogus is not found", "status": "NOT_FOUND"}},
    )
    client = _StubClient(actions=[not_found, not_found, not_found])

    with pytest.raises(InvalidGeminiModelError):
        call_gemini(
            client,
            model="bogus",
            contents=[],
            retry_policy=_fast_policy(),
        )

    assert client.models.calls == 1


def test_retries_server_error_then_succeeds() -> None:
    server_error = genai_errors.ServerError(
        500,
        {"error": {"code": 500, "message": "Internal", "status": "INTERNAL"}},
    )
    client = _StubClient(actions=[server_error], text="recovered")

    result = call_gemini(
        client,
        model="m",
        contents=[],
        retry_policy=_fast_policy(max_attempts=2),
    )

    assert result == "recovered"
    assert client.models.calls == 2


def test_timeout_raises_typed_error() -> None:
    def _slow() -> None:
        time.sleep(0.5)

    client = _StubClient(actions=[_slow])
    policy = RetryPolicy(
        max_attempts=1,
        min_backoff_seconds=0.0,
        max_backoff_seconds=0.0,
        timeout_seconds=0.05,
    )

    with pytest.raises(GeminiTimeoutError) as excinfo:
        call_gemini(client, model="m", contents=[], retry_policy=policy)

    assert excinfo.value.timeout_seconds == 0.05
    assert excinfo.value.model == "m"


def test_no_retry_policy_runs_once() -> None:
    client = _StubClient(actions=[_quota_error()])

    with pytest.raises(GeminiQuotaError):
        call_gemini(client, model="m", contents=[])

    assert client.models.calls == 1
