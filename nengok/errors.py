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


class OptionalDependencyError(NengokError):
    """
    Raised when a feature needs a package that the user did not install.

    Carries the install hint so the CLI can show `pip install nengok[extra]`
    without each call site reinventing the wording.
    """

    def __init__(self, message: str, *, install_hint: str) -> None:
        super().__init__(message)
        self.install_hint = install_hint


class MissingApiKeyError(NengokError):
    """Raised when a Gemini call site has no `GOOGLE_API_KEY` to use."""

    def __init__(self, message: str, *, role: str) -> None:
        super().__init__(message)
        self.role = role


class BaselinePromptError(NengokError):
    """Raised when no baseline prompt can be resolved for the configured project."""

    def __init__(self, message: str, *, project_identifier: str) -> None:
        super().__init__(message)
        self.project_identifier = project_identifier


class GoldenDatasetError(NengokError):
    """Raised when the bundled golden dataset is missing or unreadable."""

    def __init__(self, message: str, *, path: str) -> None:
        super().__init__(message)
        self.path = path


class PhoenixConnectionError(NengokError):
    """Raised when Phoenix is unreachable (DNS, refused connection, TLS)."""


class PhoenixProjectNotFoundError(NengokError):
    """Raised when the configured Phoenix project does not exist."""

    def __init__(self, message: str, *, project_identifier: str) -> None:
        super().__init__(message)
        self.project_identifier = project_identifier


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


class AgentRunnerLoadError(NengokError):
    """Raised when the configured agent runner cannot be imported or fails the protocol check."""

    def __init__(self, message: str, *, project_identifier: str) -> None:
        super().__init__(message)
        self.project_identifier = project_identifier
