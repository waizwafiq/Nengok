"""Error-translation behavior for the shared Gemini call wrapper."""

from __future__ import annotations

from typing import Any

import pytest
from google.genai import errors as genai_errors

from nengok.utils.gemini import (
    GeminiAuthError,
    GeminiQuotaError,
    InvalidGeminiModelError,
    call_gemini,
)


class _StubModels:
    def __init__(self, exc: Exception | None = None, text: str = "ok") -> None:
        self._exc = exc
        self._text = text
        self.last_kwargs: dict[str, Any] | None = None

    def generate_content(self, **kwargs: Any) -> Any:
        self.last_kwargs = kwargs
        if self._exc is not None:
            raise self._exc

        class _Response:
            def __init__(self, text: str) -> None:
                self.text = text

        return _Response(self._text)


class _StubClient:
    def __init__(self, exc: Exception | None = None, text: str = "ok") -> None:
        self.models = _StubModels(exc=exc, text=text)


def test_returns_text_on_success() -> None:
    client = _StubClient(text="hello")
    result = call_gemini(client, model="gemini-3.1-pro-preview", contents=[{"role": "user"}])
    assert result == "hello"
    assert client.models.last_kwargs == {
        "model": "gemini-3.1-pro-preview",
        "contents": [{"role": "user"}],
    }


def test_passes_config_when_provided() -> None:
    client = _StubClient()
    sentinel = object()
    call_gemini(client, model="m", contents=[], config=sentinel)
    assert client.models.last_kwargs is not None
    assert client.models.last_kwargs["config"] is sentinel


def test_404_translates_to_invalid_model() -> None:
    exc = genai_errors.ClientError(
        404,
        {"error": {"code": 404, "message": "models/bogus is not found", "status": "NOT_FOUND"}},
    )
    client = _StubClient(exc=exc)
    with pytest.raises(InvalidGeminiModelError, match="NENGOK_DIAGNOSER_MODEL"):
        call_gemini(
            client,
            model="bogus",
            contents=[],
            env_var_hint="NENGOK_DIAGNOSER_MODEL",
            role_hint="Clusterer",
        )


def test_400_with_invalid_model_message_translates() -> None:
    exc = genai_errors.ClientError(
        400,
        {
            "error": {
                "code": 400,
                "message": "Requested model is invalid or unsupported.",
                "status": "INVALID_ARGUMENT",
            }
        },
    )
    client = _StubClient(exc=exc)
    with pytest.raises(InvalidGeminiModelError):
        call_gemini(client, model="weird", contents=[])


def test_403_translates_to_auth_error() -> None:
    exc = genai_errors.ClientError(
        403,
        {"error": {"code": 403, "message": "Permission denied", "status": "PERMISSION_DENIED"}},
    )
    client = _StubClient(exc=exc)
    with pytest.raises(GeminiAuthError, match="GOOGLE_API_KEY"):
        call_gemini(client, model="m", contents=[])


def test_429_translates_to_quota_error() -> None:
    exc = genai_errors.ClientError(
        429,
        {"error": {"code": 429, "message": "Quota exceeded", "status": "RESOURCE_EXHAUSTED"}},
    )
    client = _StubClient(exc=exc)
    with pytest.raises(GeminiQuotaError) as excinfo:
        call_gemini(client, model="m", contents=[])
    assert excinfo.value.retry_after_seconds is None
    assert excinfo.value.quota_id is None


def test_429_parses_retry_delay_and_quota_id_from_details() -> None:
    exc = genai_errors.ClientError(
        429,
        {
            "error": {
                "code": 429,
                "message": "Quota exceeded. Please retry in 44.9s.",
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": "45s",
                    },
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}],
                    },
                ],
            }
        },
    )
    client = _StubClient(exc=exc)
    with pytest.raises(GeminiQuotaError) as excinfo:
        call_gemini(
            client,
            model="gemini-2.5-flash",
            contents=[],
            env_var_hint="SAMPLE_AGENT_MODEL",
            role_hint="Travel Planner",
        )

    err = excinfo.value
    assert err.retry_after_seconds == 45.0
    assert err.quota_id == "GenerateRequestsPerDayPerProjectPerModel-FreeTier"
    message = str(err)
    assert "Retry in 45s" in message
    assert "GenerateRequestsPerDayPerProjectPerModel-FreeTier" in message
    assert "SAMPLE_AGENT_MODEL" in message
    assert "gemini-2.5-flash" in message


def test_429_falls_back_to_message_when_details_missing() -> None:
    exc = genai_errors.ClientError(
        429,
        {
            "error": {
                "code": 429,
                "message": "Quota exceeded. Please retry in 12s.",
                "status": "RESOURCE_EXHAUSTED",
            }
        },
    )
    client = _StubClient(exc=exc)
    with pytest.raises(GeminiQuotaError) as excinfo:
        call_gemini(client, model="m", contents=[])
    assert excinfo.value.retry_after_seconds == 12.0
    assert excinfo.value.quota_id is None


def test_unhandled_apierror_reraises() -> None:
    exc = genai_errors.ServerError(
        500,
        {"error": {"code": 500, "message": "Internal", "status": "INTERNAL"}},
    )
    client = _StubClient(exc=exc)
    with pytest.raises(genai_errors.ServerError):
        call_gemini(client, model="m", contents=[])


def test_env_var_hint_is_optional() -> None:
    exc = genai_errors.ClientError(
        404,
        {"error": {"code": 404, "message": "not found", "status": "NOT_FOUND"}},
    )
    client = _StubClient(exc=exc)
    with pytest.raises(InvalidGeminiModelError) as excinfo:
        call_gemini(client, model="m", contents=[], role_hint="Tester")
    assert "Override via" not in str(excinfo.value)
