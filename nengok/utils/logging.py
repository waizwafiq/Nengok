"""
Structured logging for Nengok.

`configure_logging` installs either a human-readable text handler
(interactive `nengok run`) or a JSON handler (long-running `nengok
watch`). Every record passes through `_RedactingFilter`, which
scrubs API keys, bearer tokens, and password-like fields so secrets
never reach a log shipper.

Stage-scoped fields (`run_id`, `stage`, `cluster_id`, `latency_ms`,
`gemini_tokens`) attach via `contextvars` so any logger inside a
`run_context(...)` block tags its records automatically. Stages do
not need to thread context through call signatures.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_CONFIGURED = False

_run_id_ctx: ContextVar[str | None] = ContextVar("nengok_run_id", default=None)
_stage_ctx: ContextVar[str | None] = ContextVar("nengok_stage", default=None)
_cluster_id_ctx: ContextVar[str | None] = ContextVar("nengok_cluster_id", default=None)
_latency_ms_ctx: ContextVar[float | None] = ContextVar("nengok_latency_ms", default=None)
_gemini_tokens_ctx: ContextVar[int | None] = ContextVar("nengok_gemini_tokens", default=None)

_REDACTION_PATTERN = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|authorization)\s*[=:]\s*(?:bearer\s+)?\S+"
)

_URL_PASSWORD_PATTERN = re.compile(r"(://[^:/?#@\s]+):([^@/?#\s]+)(@)")

# Python logging level name -> Google Cloud Logging `severity` enum. The
# standard level names already match the GCP enum; NOTSET maps to DEFAULT.
_GCP_SEVERITY = {
    "CRITICAL": "CRITICAL",
    "ERROR": "ERROR",
    "WARNING": "WARNING",
    "INFO": "INFO",
    "DEBUG": "DEBUG",
    "NOTSET": "DEFAULT",
}


class _ContextFilter(logging.Filter):
    """Attach contextvars to every record so the formatter can render them."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = _run_id_ctx.get()
        record.stage = _stage_ctx.get()
        record.cluster_id = _cluster_id_ctx.get()
        record.latency_ms = _latency_ms_ctx.get()
        record.gemini_tokens = _gemini_tokens_ctx.get()
        return True


class _RedactingFilter(logging.Filter):
    """Scrub secret-shaped substrings from every formatted message."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _scrub(record.msg)
        if record.args:
            scrubbed: list[Any] = []
            for arg in record.args if isinstance(record.args, tuple) else (record.args,):
                if isinstance(arg, str):
                    scrubbed.append(_scrub(arg))
                else:
                    scrubbed.append(arg)
            record.args = tuple(scrubbed) if isinstance(record.args, tuple) else scrubbed[0]
        return True


def _scrub(value: str) -> str:
    """Apply every redaction pattern to `value` and return the masked result."""
    value = _URL_PASSWORD_PATTERN.sub(_redact_url_password, value)
    return _REDACTION_PATTERN.sub(_redact_match, value)


def _redact_match(match: re.Match[str]) -> str:
    return f"{match.group(1)}=<redacted>"


def _redact_url_password(match: re.Match[str]) -> str:
    """Mask the password segment of a URL like `scheme://user:secret@host`."""
    return f"{match.group(1)}:***{match.group(3)}"


def configure_logging(
    *,
    verbose: bool = False,
    json_format: bool = False,
    log_format: str | None = None,
    level: str | None = None,
) -> None:
    """
    Install root-logger handlers; calling again replaces them.

    ``log_format`` selects the formatter explicitly: ``"text"`` (human),
    ``"json"`` (the long-standing ``nengok watch`` shape), or ``"gcp"``
    (Cloud Logging, with a top-level ``severity`` field instead of
    ``level``). When ``log_format`` is None it falls back to
    ``json_format`` so existing callers keep working.
    """
    if level is not None:
        resolved_level = getattr(logging, level.upper(), logging.INFO)
    else:
        resolved_level = logging.DEBUG if verbose else logging.INFO

    fmt = (log_format or ("json" if json_format else "text")).strip().lower()

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(_build_formatter(fmt=fmt))
    handler.addFilter(_ContextFilter())
    handler.addFilter(_RedactingFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(resolved_level)

    # The ADK logs under the "google_adk" prefix (not "google.adk"),
    # google-genai under "google_genai", and mcp is the ADK toolset's
    # client library; cap all three so the cycle log stays readable.
    # Their records still pass through the root handler (and so the
    # redacting filter) at WARNING and above.
    for noisy in ("httpx", "httpcore", "urllib3", "openinference", "google_adk", "google_genai", "mcp"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    global _CONFIGURED
    _CONFIGURED = True


def _build_formatter(*, fmt: str) -> logging.Formatter:
    if fmt == "gcp":
        from pythonjsonlogger.json import JsonFormatter

        class _GcpFormatter(JsonFormatter):
            """Emit Cloud Logging's ``severity`` special field, not ``level``."""

            def add_fields(
                self,
                log_record: dict[str, Any],
                record: logging.LogRecord,
                message_dict: dict[str, Any],
            ) -> None:
                super().add_fields(log_record, record, message_dict)
                log_record["severity"] = _GCP_SEVERITY.get(record.levelname, record.levelname or "DEFAULT")
                log_record.pop("level", None)
                log_record.pop("levelname", None)

        # No asctime: Cloud Run stamps each entry. severity replaces level.
        return _GcpFormatter(
            "%(name)s %(message)s " "%(run_id)s %(stage)s %(cluster_id)s %(latency_ms)s %(gemini_tokens)s",
            rename_fields={"name": "logger"},
        )

    if fmt == "json":
        from pythonjsonlogger.json import JsonFormatter

        return JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s "
            "%(run_id)s %(stage)s %(cluster_id)s %(latency_ms)s %(gemini_tokens)s",
            rename_fields={
                "asctime": "timestamp",
                "levelname": "level",
                "name": "logger",
            },
        )

    return logging.Formatter(
        fmt="%(asctime)s %(levelname)-7s %(name)s :: %(message)s",
        datefmt="%H:%M:%S",
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


@contextmanager
def run_context(
    *,
    run_id: str | None = None,
    stage: str | None = None,
    cluster_id: str | None = None,
    latency_ms: float | None = None,
    gemini_tokens: int | None = None,
) -> Iterator[None]:
    """
    Tag every log record inside the block with these context fields.

    Each field that is not explicitly set carries the value from the
    enclosing `run_context`, so the orchestrator can nest a per-stage
    block inside a per-cycle block without re-stating `run_id`.
    """
    tokens: list[Any] = []
    if run_id is not None:
        tokens.append(_run_id_ctx.set(run_id))
    if stage is not None:
        tokens.append(_stage_ctx.set(stage))
    if cluster_id is not None:
        tokens.append(_cluster_id_ctx.set(cluster_id))
    if latency_ms is not None:
        tokens.append(_latency_ms_ctx.set(latency_ms))
    if gemini_tokens is not None:
        tokens.append(_gemini_tokens_ctx.set(gemini_tokens))
    try:
        yield
    finally:
        for token in reversed(tokens):
            token.var.reset(token)


def reset_for_tests() -> None:
    """Drop the configured-once latch; tests need to re-install handlers."""
    global _CONFIGURED
    _CONFIGURED = False
