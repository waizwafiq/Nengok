"""End-to-end: run experiments against a live Phoenix instance."""

from __future__ import annotations

import uuid

import pytest

from nengok.config import NengokConfig
from nengok.core.evaluators.code_evals import default_code_evaluators
from nengok.core.types import RegressionTestCase
from nengok.phoenix.client import PhoenixWrapper


@pytest.mark.slow
def test_run_experiment_pass_rate_is_perfect(phoenix_config: NengokConfig) -> None:
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
        experiment_name=f"harness-smoke-{uuid.uuid4().hex[:6]}",
        dry_run=1,
    )
    assert result.pass_rate == 1.0
    assert len(result.per_case) == 1


@pytest.mark.slow
def test_two_golden_experiments_have_distinct_names(phoenix_config: NengokConfig) -> None:
    wrapper = PhoenixWrapper(phoenix_config)
    from nengok.core.fixer.loaders import SAMPLE_AGENT_PROMPT_PATH

    prompt = SAMPLE_AGENT_PROMPT_PATH.read_text(encoding="utf-8")
    baseline_run, fix_run = wrapper.run_golden_comparison(
        baseline_prompt=prompt,
        proposed_prompt=prompt,
        evaluators=default_code_evaluators(),
    )
    assert baseline_run.experiment_id is not None
    assert fix_run.experiment_id is not None
    assert baseline_run.experiment_id != fix_run.experiment_id


@pytest.mark.slow
def test_attach_evaluators_adds_scores_without_rerun(phoenix_config: NengokConfig) -> None:
    wrapper = PhoenixWrapper(phoenix_config)
    cases = [
        RegressionTestCase(
            case_id=str(uuid.uuid4()),
            input={"prompt": "harness ping"},
            expected={"contains": "pong"},
            metadata={},
        )
    ]
    dataset_ref = wrapper.create_dataset(name=f"nengok-harness-eval-{uuid.uuid4().hex[:8]}", cases=cases)
    run = wrapper.run_experiment(
        dataset_ref=dataset_ref,
        prompt="You always reply with the literal word 'pong'.",
        evaluators=default_code_evaluators(),
        experiment_name=f"harness-eval-base-{uuid.uuid4().hex[:6]}",
        dry_run=1,
    )
    assert run.experiment_id is not None

    wrapper.attach_evaluators(
        experiment_id=run.experiment_id,
        evaluators=default_code_evaluators(),
    )
    # experiment_id is unchanged — attach_evaluators adds evals, not a new experiment
    assert run.experiment_id is not None
