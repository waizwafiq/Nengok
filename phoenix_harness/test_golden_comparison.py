"""Live Phoenix harness: run both prompts against the golden dataset."""

from __future__ import annotations

import pytest

from nengok.config import NengokConfig
from nengok.core.evaluators.code_evals import default_code_evaluators
from nengok.core.fixer.loaders import SAMPLE_AGENT_PROMPT_PATH
from nengok.phoenix.client import PhoenixWrapper


@pytest.mark.slow
def test_golden_comparison_both_prompts_pass(phoenix_config: NengokConfig) -> None:
    wrapper = PhoenixWrapper(phoenix_config)
    prompt = SAMPLE_AGENT_PROMPT_PATH.read_text(encoding="utf-8")

    baseline_run, fix_run = wrapper.run_golden_comparison(
        baseline_prompt=prompt,
        proposed_prompt=prompt,
        evaluators=default_code_evaluators(),
    )

    assert baseline_run.pass_rate > 0.0
    assert fix_run.pass_rate > 0.0
    assert baseline_run.experiment_id != fix_run.experiment_id
