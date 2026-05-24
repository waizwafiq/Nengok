"""
The pass/fail gate that decides whether a fix is promoted to a
human-approval artifact or escalated.

Thresholds come from `NengokConfig`:

  - Regression set pass rate must be >= `regression_pass_threshold` (0.90).
  - Golden set regression (baseline -> fix delta) must be <= `golden_regression_limit` (0.02).
"""

from __future__ import annotations

from dataclasses import dataclass

from nengok.config import NengokConfig
from nengok.core.types import ExperimentResult, Verification, VerificationOutcome
from nengok.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class VerifierGate:
    config: NengokConfig

    def evaluate(self, result: ExperimentResult) -> Verification:
        if result.fix_pass_rate < self.config.regression_pass_threshold:
            return Verification(
                outcome=VerificationOutcome.FAILED_REGRESSION,
                experiment=result,
                notes=(
                    f"Fix pass rate {result.fix_pass_rate:.0%} is below "
                    f"the {self.config.regression_pass_threshold:.0%} threshold."
                ),
            )

        regression_delta = result.golden_baseline_pass_rate - result.golden_fix_pass_rate
        if regression_delta > self.config.golden_regression_limit:
            return Verification(
                outcome=VerificationOutcome.FAILED_GOLDEN,
                experiment=result,
                notes=(
                    f"Golden-set regression {regression_delta:.0%} exceeds "
                    f"the {self.config.golden_regression_limit:.0%} ceiling."
                ),
            )

        return Verification(outcome=VerificationOutcome.PASSED, experiment=result)
