"""Phoenix wrapper unit tests covering experiment wiring."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from nengok.config import NengokConfig
from nengok.core.evaluators.code_evals import output_is_present
from nengok.phoenix.client import PhoenixWrapper
from nengok.runners.agent_runner import register_runner

TEST_PROJECT = "phoenix-client-test-project"


def _stub_ran_experiment(
    *,
    task_outputs: list[dict[str, Any]] | None = None,
    code_score: float = 1.0,
) -> dict[str, Any]:
    outputs = task_outputs or [{"itinerary": "ok-1"}, {"itinerary": "ok-2"}]
    task_runs = [
        {
            "id": f"run-{idx}",
            "dataset_example_id": f"ex-{idx}",
            "output": output,
            "error": None,
        }
        for idx, output in enumerate(outputs)
    ]
    evaluation_runs = [
        {
            "experiment_run_id": run["id"],
            "name": "output_is_present",
            "result": {"name": "output_is_present", "score": code_score},
        }
        for run in task_runs
    ]
    return {
        "experiment_id": "exp-stub-1",
        "task_runs": task_runs,
        "evaluation_runs": evaluation_runs,
    }


class _FakeExperiments:
    def __init__(self, ran: dict[str, Any]) -> None:
        self._ran = ran
        self.calls: list[dict[str, Any]] = []

    def run_experiment(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        for example in [{"input": {"query": "first"}}, {"input": {"query": "second"}}]:
            kwargs["task"](example)
        return self._ran


class _FakeClient:
    def __init__(self, ran: dict[str, Any]) -> None:
        self.experiments = _FakeExperiments(ran)


@pytest.fixture
def experiment_config(tmp_config: NengokConfig) -> NengokConfig:
    return replace(tmp_config, project_identifier=TEST_PROJECT)


@pytest.fixture
def runner_calls() -> list[tuple[dict[str, Any], str]]:
    captured: list[tuple[dict[str, Any], str]] = []

    def fake_runner(input_row: dict[str, Any], prompt: str) -> dict[str, Any]:
        captured.append((input_row, prompt))
        return {"itinerary": f"itin for {input_row.get('query', '')}"}

    register_runner(TEST_PROJECT, fake_runner)
    return captured


def test_run_experiment_wires_runner_and_pass_rate(
    experiment_config: NengokConfig,
    runner_calls: list[tuple[dict[str, Any], str]],
) -> None:
    wrapper = PhoenixWrapper(experiment_config)
    fake_client = _FakeClient(_stub_ran_experiment())
    wrapper._client = fake_client

    result = wrapper.run_experiment(
        dataset_ref={"name": "ds"},
        prompt="CANDIDATE-PROMPT",
        evaluators=[output_is_present],
        experiment_name="exp-1",
        dry_run=0,
    )

    assert result.experiment_id == "exp-stub-1"
    assert result.pass_rate == 1.0
    assert len(result.per_case) == 2
    assert [call[0]["query"] for call in runner_calls] == ["first", "second"]
    assert all(call[1] == "CANDIDATE-PROMPT" for call in runner_calls)


def test_run_experiment_passes_dry_run_and_evaluator_set(
    experiment_config: NengokConfig,
    runner_calls: list[tuple[dict[str, Any], str]],
) -> None:
    del runner_calls
    wrapper = PhoenixWrapper(experiment_config)
    fake_client = _FakeClient(_stub_ran_experiment())
    wrapper._client = fake_client

    wrapper.run_experiment(
        dataset_ref={"name": "ds"},
        prompt="P",
        evaluators=[output_is_present],
        experiment_name="exp-1",
        dry_run=3,
    )

    sent = fake_client.experiments.calls[0]
    assert sent["dry_run"] == 3
    assert sent["experiment_name"] == "exp-1"
    assert sent["evaluators"] == [output_is_present]


def test_run_experiment_fails_when_runner_missing(
    tmp_config: NengokConfig,
) -> None:
    config = replace(tmp_config, project_identifier="never-registered-project")
    wrapper = PhoenixWrapper(config)
    wrapper._client = _FakeClient(_stub_ran_experiment())

    with pytest.raises(RuntimeError, match="No agent runner registered"):
        wrapper.run_experiment(
            dataset_ref={"name": "ds"},
            prompt="P",
            evaluators=[output_is_present],
            experiment_name="exp-1",
            dry_run=0,
        )


def test_run_experiment_failing_code_eval_drops_pass_rate(
    experiment_config: NengokConfig,
    runner_calls: list[tuple[dict[str, Any], str]],
) -> None:
    del runner_calls
    wrapper = PhoenixWrapper(experiment_config)
    wrapper._client = _FakeClient(_stub_ran_experiment(code_score=0.0))

    result = wrapper.run_experiment(
        dataset_ref={"name": "ds"},
        prompt="P",
        evaluators=[output_is_present],
        experiment_name="exp-1",
        dry_run=0,
    )

    assert result.pass_rate == 0.0
