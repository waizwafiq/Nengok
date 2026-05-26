"""
Typed exception hierarchy for Nengok.

Centralizing these here lets the CLI catch each class once and print a
tailored hint, instead of unwinding a stack trace into the user's
terminal. Phase 6.1 expands this module with config and runner errors;
Phase 5.2 seeds it with the Phoenix timeout class.
"""

from __future__ import annotations


class NengokError(RuntimeError):
    """Base class for Nengok-specific failures."""


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
