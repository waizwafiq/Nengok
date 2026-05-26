"""Verify the CLI dispatcher prints tailored hints per typed exception class."""

from __future__ import annotations

from _pytest.capture import CaptureFixture

from nengok.cli import _error_label, _report_external_error
from nengok.errors import (
    AgentRunnerLoadError,
    BaselinePromptError,
    GoldenDatasetError,
    MissingApiKeyError,
    OptionalDependencyError,
    PhoenixConnectionError,
    PhoenixProjectNotFoundError,
)
from nengok.utils.gemini import GeminiAuthError, GeminiQuotaError


def _stderr(capsys: CaptureFixture[str]) -> str:
    return capsys.readouterr().err


def test_missing_api_key_classifier(capsys: CaptureFixture[str]) -> None:
    exc = MissingApiKeyError("clusterer needs a key", role="Clusterer")

    _report_external_error(exc)

    err = _stderr(capsys)
    assert "Error (missing-api-key): clusterer needs a key" in err


def test_optional_dependency_includes_install_hint(capsys: CaptureFixture[str]) -> None:
    exc = OptionalDependencyError("phoenix missing", install_hint="pip install nengok[phoenix]")

    _report_external_error(exc)

    err = _stderr(capsys)
    assert "missing-dependency" in err
    assert "Fix: pip install nengok[phoenix]" in err


def test_gemini_quota_emits_retry_and_quota(capsys: CaptureFixture[str]) -> None:
    exc = GeminiQuotaError(
        "rate limited",
        retry_after_seconds=42.0,
        quota_id="GenerateRequestsPerDayPerProjectPerModel-FreeTier",
    )

    _report_external_error(exc)

    err = _stderr(capsys)
    assert "gemini-quota" in err
    assert "Retry after: 42s" in err
    assert "Quota id: GenerateRequestsPerDayPerProjectPerModel-FreeTier" in err


def test_prefix_is_used(capsys: CaptureFixture[str]) -> None:
    exc = GeminiAuthError("bad key")

    _report_external_error(exc, prefix="Cycle skipped in 'diagnoser'")

    err = _stderr(capsys)
    assert err.startswith("Cycle skipped in 'diagnoser' (gemini-auth):")


def test_error_label_covers_every_typed_class() -> None:
    cases: list[tuple[Exception, str]] = [
        (MissingApiKeyError("x", role="r"), "missing-api-key"),
        (OptionalDependencyError("x", install_hint="y"), "missing-dependency"),
        (BaselinePromptError("x", project_identifier="p"), "missing-baseline-prompt"),
        (GoldenDatasetError("x", path="/p"), "golden-dataset-missing"),
        (AgentRunnerLoadError("x", project_identifier="p"), "agent-runner-not-registered"),
        (PhoenixConnectionError("x"), "phoenix-unreachable"),
        (PhoenixProjectNotFoundError("x", project_identifier="p"), "phoenix-project-missing"),
        (GeminiAuthError("x"), "gemini-auth"),
        (GeminiQuotaError("x"), "gemini-quota"),
    ]

    for exc, expected in cases:
        assert _error_label(exc) == expected, f"{type(exc).__name__} -> {expected}"
