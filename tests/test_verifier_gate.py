"""Verifier-gate decision matrix."""

from __future__ import annotations

from pathlib import Path

from nengok.config import NengokConfig
from nengok.core.types import ExperimentResult, VerificationOutcome
from nengok.core.verifier.gate import VerifierGate


def _config() -> NengokConfig:
    return NengokConfig.load(
        config_path=Path("/nonexistent-nengok-config.toml"),
        phoenix_base_url="http://localhost:6006",
    )


def test_passing_experiment_is_promoted() -> None:
    gate = VerifierGate(_config())
    result = ExperimentResult(
        experiment_name="x",
        dataset_name="d",
        baseline_pass_rate=0.4,
        fix_pass_rate=0.95,
        golden_baseline_pass_rate=1.0,
        golden_fix_pass_rate=1.0,
    )
    assert gate.evaluate(result).outcome is VerificationOutcome.PASSED


def test_low_regression_pass_rate_fails() -> None:
    gate = VerifierGate(_config())
    result = ExperimentResult(
        experiment_name="x",
        dataset_name="d",
        baseline_pass_rate=0.4,
        fix_pass_rate=0.5,
        golden_baseline_pass_rate=1.0,
        golden_fix_pass_rate=1.0,
    )
    assert gate.evaluate(result).outcome is VerificationOutcome.FAILED_REGRESSION


def test_golden_regression_fails() -> None:
    gate = VerifierGate(_config())
    result = ExperimentResult(
        experiment_name="x",
        dataset_name="d",
        baseline_pass_rate=0.4,
        fix_pass_rate=0.99,
        golden_baseline_pass_rate=1.0,
        golden_fix_pass_rate=0.90,
    )
    assert gate.evaluate(result).outcome is VerificationOutcome.FAILED_GOLDEN
