"""
Friendly wrappers around `google-genai` Gemini calls.

Translates the raw `google.genai.errors.APIError` family into a small
set of named exceptions that point the user at the env var or config
field they configured. A typo in `NENGOK_DIAGNOSER_MODEL` fails with
`InvalidGeminiModelError: ... is not a valid Gemini model` instead of
unwinding a stack trace from inside the SDK.
"""

from __future__ import annotations

import re
from typing import Any


class GeminiCallError(RuntimeError):
    """Base class for translated Gemini call failures."""


class InvalidGeminiModelError(GeminiCallError):
    """Raised when the configured Gemini model id is not accepted by the API."""


class GeminiAuthError(GeminiCallError):
    """Raised when the API key is missing, expired, or unauthorized for this model."""


class GeminiQuotaError(GeminiCallError):
    """
    Raised when the call hit a 429 rate-limit or quota cap.

    `retry_after_seconds` is parsed from the `RetryInfo` block Google
    attaches to the error and is None when the API does not include
    one. `quota_id` is the Google quota identifier
    (e.g. `GenerateRequestsPerDayPerProjectPerModel-FreeTier`) so the
    caller can tell a daily-cap from a per-minute throttle.
    """

    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: float | None = None,
        quota_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
        self.quota_id = quota_id


_RETRY_DELAY_PATTERN = re.compile(r"^(\d+(?:\.\d+)?)s$")
_RETRY_IN_MESSAGE_PATTERN = re.compile(r"retry in (\d+(?:\.\d+)?)\s*s", re.IGNORECASE)


def call_gemini(
    client: Any,
    *,
    model: str,
    contents: Any,
    config: Any = None,
    env_var_hint: str | None = None,
    role_hint: str | None = None,
) -> str:
    """
    Invoke `client.models.generate_content` and translate API errors.

    `env_var_hint` is the name of the env var the caller's `model`
    value came from (e.g. `"NENGOK_DIAGNOSER_MODEL"`). It is woven
    into the error message so a misconfiguration points back at the
    knob the user actually turned. `role_hint` names the pipeline
    stage (e.g. `"Clusterer"`) so multi-stage runs are debuggable
    from the error alone.
    """
    try:
        from google.genai import errors as genai_errors
    except ImportError as exc:
        raise RuntimeError("google-genai is not installed; install with the `gemini` extra.") from exc

    kwargs: dict[str, Any] = {"model": model, "contents": contents}
    if config is not None:
        kwargs["config"] = config

    try:
        response = client.models.generate_content(**kwargs)
    except genai_errors.APIError as exc:
        _translate_and_raise(exc, model=model, env_var_hint=env_var_hint, role_hint=role_hint)

    return response.text or ""


def _translate_and_raise(
    exc: Exception,
    *,
    model: str,
    env_var_hint: str | None,
    role_hint: str | None,
) -> None:
    code: int | None = getattr(exc, "code", None)
    status: str = (getattr(exc, "status", "") or "").upper()
    message: str = getattr(exc, "message", "") or str(exc)
    role: str = role_hint or "Gemini call"
    override_hint: str = f" Override via the {env_var_hint} env var." if env_var_hint else ""

    if _looks_like_invalid_model(code, status, message):
        raise InvalidGeminiModelError(
            f"{role}: model {model!r} is not a valid Gemini model."
            f"{override_hint} Google API said: {message or status or code}"
        ) from exc

    if code in {401, 403} or status in {"UNAUTHENTICATED", "PERMISSION_DENIED"}:
        raise GeminiAuthError(
            f"{role}: Gemini rejected the request ({code} {status}). "
            "Check that GOOGLE_API_KEY is set to a valid AI Studio key with access "
            f"to model {model!r}."
        ) from exc

    if code == 429 or status in {"RESOURCE_EXHAUSTED", "TOO_MANY_REQUESTS"}:
        retry_after = _parse_retry_after(exc, message)
        quota_id = _parse_quota_id(exc)
        retry_hint = f" Retry in {retry_after:.0f}s." if retry_after is not None else ""
        quota_hint = f" Quota hit: {quota_id}." if quota_id else ""
        guidance = (
            " Free-tier daily caps reset at midnight Pacific; raise the cap at "
            "https://ai.dev/rate-limit or switch model via "
            f"{env_var_hint}."
            if env_var_hint
            else " Raise the cap at https://ai.dev/rate-limit."
        )
        raise GeminiQuotaError(
            f"{role}: Gemini quota or rate limit exhausted ({code} {status}) for model {model!r}."
            f"{retry_hint}{quota_hint}{guidance}",
            retry_after_seconds=retry_after,
            quota_id=quota_id,
        ) from exc

    raise


def _parse_retry_after(exc: Exception, message: str) -> float | None:
    """Extract the API-suggested retry delay in seconds, if present."""
    details: list[Any] = getattr(exc, "details", None) or []
    if isinstance(details, dict):
        details = details.get("error", {}).get("details") or []
    for detail in details:
        if not isinstance(detail, dict):
            continue
        if detail.get("@type", "").endswith("google.rpc.RetryInfo"):
            raw = detail.get("retryDelay")
            if isinstance(raw, str):
                match = _RETRY_DELAY_PATTERN.match(raw.strip())
                if match:
                    return float(match.group(1))
    match = _RETRY_IN_MESSAGE_PATTERN.search(message)
    if match:
        return float(match.group(1))
    return None


def _parse_quota_id(exc: Exception) -> str | None:
    """Extract the `quotaId` from the first QuotaFailure violation, if present."""
    details: list[Any] = getattr(exc, "details", None) or []
    if isinstance(details, dict):
        details = details.get("error", {}).get("details") or []
    for detail in details:
        if not isinstance(detail, dict):
            continue
        if detail.get("@type", "").endswith("google.rpc.QuotaFailure"):
            violations = detail.get("violations") or []
            if violations and isinstance(violations[0], dict):
                quota_id = violations[0].get("quotaId")
                if isinstance(quota_id, str):
                    return quota_id
    return None


def _looks_like_invalid_model(code: int | None, status: str, message: str) -> bool:
    if code == 404 or status == "NOT_FOUND":
        return True
    message_lower = message.lower()
    if code == 400 and "model" in message_lower:
        return any(token in message_lower for token in ("not found", "invalid", "unsupported"))
    return False
