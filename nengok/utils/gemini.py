"""
Friendly wrappers around `google-genai` Gemini calls.

Translates the raw `google.genai.errors.APIError` family into a small
set of named exceptions that point the user at the env var or config
field they configured. A typo in `NENGOK_DIAGNOSER_MODEL` fails with
`InvalidGeminiModelError: ... is not a valid Gemini model` instead of
unwinding a stack trace from inside the SDK.

When the caller threads a `RetryPolicy` through, the wrapper retries
quota and 5xx failures with exponential backoff and enforces a
per-attempt wall-clock timeout. Authentication and invalid-model
errors are terminal and fail fast.
"""

from __future__ import annotations

import concurrent.futures
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from nengok.utils.logging import get_logger

if TYPE_CHECKING:
    from nengok.config import NengokConfig
    from nengok.core.cost import CostTracker

logger = get_logger(__name__)


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


class GeminiTimeoutError(GeminiCallError):
    """Raised when a Gemini call exceeds the per-call wall-clock timeout."""

    def __init__(self, message: str, *, timeout_seconds: float, model: str) -> None:
        super().__init__(message)
        self.timeout_seconds = timeout_seconds
        self.model = model


@dataclass(frozen=True)
class RetryPolicy:
    """Tenacity retry knobs for a single Gemini call site."""

    max_attempts: int = 3
    min_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 16.0
    timeout_seconds: float = 45.0

    @classmethod
    def from_config(cls, config: NengokConfig) -> RetryPolicy:
        return cls(
            max_attempts=config.gemini_max_retries,
            min_backoff_seconds=config.gemini_min_retry_backoff_seconds,
            timeout_seconds=config.gemini_timeout_seconds,
        )


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
    retry_policy: RetryPolicy | None = None,
    cost_tracker: CostTracker | None = None,
) -> str:
    """
    Invoke `client.models.generate_content` and translate API errors.

    `env_var_hint` is the name of the env var the caller's `model`
    value came from (e.g. `"NENGOK_DIAGNOSER_MODEL"`). It is woven
    into the error message so a misconfiguration points back at the
    knob the user actually turned. `role_hint` names the pipeline
    stage (e.g. `"Clusterer"`) so multi-stage runs are debuggable
    from the error alone.

    When `retry_policy` is provided, quota and 5xx failures retry with
    exponential backoff and each attempt is wrapped in a wall-clock
    timeout. Auth and invalid-model errors short-circuit out without
    retrying. When `retry_policy` is None, the call runs once with no
    timeout for backwards compatibility with callers that manage
    retries themselves.

    When `cost_tracker` is provided, the per-call `usage_metadata`
    counts feed the per-cycle budget. Stages share one tracker per
    cycle through the orchestrator.
    """
    try:
        from google.genai import errors as genai_errors
    except ImportError as exc:
        raise RuntimeError("google-genai is not installed; install with the `gemini` extra.") from exc

    def _attempt() -> str:
        return _invoke_once(
            client,
            genai_errors=genai_errors,
            model=model,
            contents=contents,
            config=config,
            env_var_hint=env_var_hint,
            role_hint=role_hint,
            timeout_seconds=retry_policy.timeout_seconds if retry_policy else None,
            cost_tracker=cost_tracker,
        )

    if retry_policy is None or retry_policy.max_attempts <= 1:
        return _attempt()

    retryer = retry(
        reraise=True,
        stop=stop_after_attempt(retry_policy.max_attempts),
        wait=wait_exponential(
            multiplier=retry_policy.min_backoff_seconds,
            min=retry_policy.min_backoff_seconds,
            max=retry_policy.max_backoff_seconds,
        ),
        retry=retry_if_exception(lambda exc: _is_retryable(exc, genai_errors=genai_errors)),
        before_sleep=_log_retry_attempt,
    )
    return retryer(_attempt)()


def _invoke_once(
    client: Any,
    *,
    genai_errors: Any,
    model: str,
    contents: Any,
    config: Any,
    env_var_hint: str | None,
    role_hint: str | None,
    timeout_seconds: float | None,
    cost_tracker: CostTracker | None,
) -> str:
    kwargs: dict[str, Any] = {"model": model, "contents": contents}
    if config is not None:
        kwargs["config"] = config

    def runner() -> Any:
        return client.models.generate_content(**kwargs)

    try:
        response = _run_with_timeout(
            runner, timeout_seconds=timeout_seconds, model=model, role_hint=role_hint
        )
    except genai_errors.APIError as exc:
        _translate_and_raise(exc, model=model, env_var_hint=env_var_hint, role_hint=role_hint)

    if cost_tracker is not None:
        _record_usage(cost_tracker, response)

    return response.text or ""


def _record_usage(cost_tracker: CostTracker, response: Any) -> None:
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return
    prompt_tokens = getattr(usage, "prompt_token_count", None) or 0
    completion_tokens = getattr(usage, "candidates_token_count", None) or 0
    cost_tracker.record(
        prompt_tokens=int(prompt_tokens),
        completion_tokens=int(completion_tokens),
    )


def _run_with_timeout(
    fn: Any,
    *,
    timeout_seconds: float | None,
    model: str,
    role_hint: str | None,
) -> Any:
    if timeout_seconds is None or timeout_seconds <= 0:
        return fn()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(fn)
        try:
            return future.result(timeout=timeout_seconds)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            role = role_hint or "Gemini call"
            raise GeminiTimeoutError(
                f"{role}: timed out after {timeout_seconds:.1f}s for model {model!r}.",
                timeout_seconds=timeout_seconds,
                model=model,
            ) from exc


def _is_retryable(exc: BaseException, *, genai_errors: Any) -> bool:
    if isinstance(exc, GeminiQuotaError | GeminiTimeoutError):
        return True
    return isinstance(exc, genai_errors.ServerError)


def _log_retry_attempt(retry_state: RetryCallState) -> None:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    delay = retry_state.next_action.sleep if retry_state.next_action else 0.0
    logger.warning(
        "Gemini retry attempt=%d delay=%.2fs error=%s",
        retry_state.attempt_number,
        delay,
        type(exc).__name__ if exc is not None else "unknown",
    )


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
