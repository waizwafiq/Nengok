"""
Typed exception hierarchy for Nengok.

Centralizing these lets the CLI catch each class once and print a
tailored hint, instead of unwinding a stack trace into the user's
terminal.
"""

from __future__ import annotations


class NengokError(RuntimeError):
    """Base class for Nengok-specific failures."""


class ConfigError(NengokError):
    """Raised when the loaded configuration is missing, malformed, or out of range."""


class PhoenixConnectionError(NengokError):
    """Raised when Phoenix is unreachable (DNS, refused connection, TLS)."""


class PhoenixProjectNotFoundError(NengokError):
    """Raised when the configured Phoenix project does not exist."""


class PhoenixTimeoutError(NengokError):
    """Raised when a Phoenix client call exceeds its configured timeout."""

    def __init__(
        self,
        message: str,
        *,
        method: str,
        timeout_seconds: float,
        observed_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.method = method
        self.timeout_seconds = timeout_seconds
        self.observed_seconds = observed_seconds


class GeminiQuotaExceededError(NengokError):
    """Raised when the Gemini API returns a quota / rate-limit failure."""


class GeminiAuthError(NengokError):
    """Raised when Gemini rejects the API key (401/403)."""


class AgentRunnerLoadError(NengokError):
    """Raised when the configured agent runner cannot be imported or fails the protocol check."""
