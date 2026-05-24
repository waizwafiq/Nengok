"""End-to-end: run a tiny experiment and confirm we get a pass-rate back."""

from __future__ import annotations

import uuid

import pytest

from nengok.config import NengokConfig
from nengok.core.evaluators.code_evals import default_code_evaluators
from nengok.core.types import RegressionTestCase
from nengok.phoenix.client import PhoenixWrapper


@pytest.mark.slow
def test_run_experiment_pass_rate_in_unit_interval(phoenix_config: NengokConfig) -> None:
    wrapper = PhoenixWrapper(phoenix_config)
    cases = [
        RegressionTestCase(
            case_id=str(uuid.uuid4()),
            input={"prompt": "harness ping"},
            expected={"contains": "pong"},
            metadata={},
        )
    ]
    dataset_ref = wrapper.create_dataset(name=f"nengok-harness-exp-{uuid.uuid4().hex[:8]}", cases=cases)
    result = wrapper.run_experiment(
        dataset_ref=dataset_ref,
        prompt="You always reply with the literal word 'pong'.",
        evaluators=default_code_evaluators(),
        experiment_name="harness-smoke",
        dry_run=1,
    )
    assert 0.0 <= result.pass_rate <= 1.0
