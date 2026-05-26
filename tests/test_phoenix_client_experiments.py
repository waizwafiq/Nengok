"""Phoenix wrapper unit tests covering experiment wiring."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from nengok.config import NengokConfig
from nengok.core.evaluators.code_evals import output_is_present
from nengok.phoenix.client import PhoenixWrapper
from nengok.runners.agent_runner import SAMPLE_AGENT_PROJECT, register_runner

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


def test_run_experiment_accepts_phoenix_dataclass_evaluation_runs(
    experiment_config: NengokConfig,
    runner_calls: list[tuple[dict[str, Any], str]],
) -> None:
    """Regression: Phoenix returns ExperimentEvaluationRun dataclasses, not dicts."""
    del runner_calls
    from datetime import UTC, datetime

    experiments_module = pytest.importorskip(
        "phoenix.client.resources.experiments",
        reason="phoenix extra not installed; this regression test needs the real dataclass.",
    )
    ExperimentEvaluationRun = experiments_module.ExperimentEvaluationRun

    base = _stub_ran_experiment()
    now = datetime.now(UTC)
    base["evaluation_runs"] = [
        ExperimentEvaluationRun(
            experiment_run_id=run["experiment_run_id"],
            start_time=now,
            end_time=now,
            name=run["name"],
            annotator_kind="CODE",
            result=run["result"],
        )
        for run in base["evaluation_runs"]
    ]

    wrapper = PhoenixWrapper(experiment_config)
    wrapper._client = _FakeClient(base)

    result = wrapper.run_experiment(
        dataset_ref={"name": "ds"},
        prompt="P",
        evaluators=[output_is_present],
        experiment_name="exp-1",
        dry_run=0,
    )

    assert result.pass_rate == 1.0
    assert len(result.per_case) == 2


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


class _GoldenDatasets:
    def __init__(self, existing: bool) -> None:
        self.existing = existing
        self.create_calls: list[dict[str, Any]] = []
        self.get_calls: list[str] = []

    def get_dataset(self, *, dataset: str) -> Any:
        self.get_calls.append(dataset)
        if self.existing:
            return {"name": dataset, "source": "lookup"}
        raise ValueError(f"dataset {dataset} not found")

    def create_dataset(self, **kwargs: Any) -> Any:
        self.create_calls.append(kwargs)
        return {"name": kwargs["name"], "source": "created"}


class _GoldenClient:
    def __init__(self, *, ran: dict[str, Any], dataset_existing: bool) -> None:
        self.datasets = _GoldenDatasets(existing=dataset_existing)
        self.experiments = _FakeExperiments(ran)


@pytest.fixture
def sample_agent_runner_registered() -> None:
    def runner(input_row: dict[str, Any], prompt: str) -> dict[str, Any]:
        del prompt
        return {"itinerary": f"plan-for-{input_row.get('query', '')}"}

    register_runner(SAMPLE_AGENT_PROJECT, runner)


def test_run_golden_comparison_creates_dataset_when_missing(
    tmp_config: NengokConfig,
    sample_agent_runner_registered: None,
) -> None:
    del sample_agent_runner_registered
    config = replace(tmp_config, project_identifier=SAMPLE_AGENT_PROJECT)
    wrapper = PhoenixWrapper(config)
    wrapper._client = _GoldenClient(ran=_stub_ran_experiment(), dataset_existing=False)

    baseline, fix = wrapper.run_golden_comparison(
        baseline_prompt="BASE",
        proposed_prompt="FIX",
        evaluators=[output_is_present],
    )

    assert baseline.pass_rate == 1.0
    assert fix.pass_rate == 1.0
    datasets = wrapper._client.datasets
    assert datasets.get_calls == ["travel-planner-golden-v2"]
    assert len(datasets.create_calls) == 1
    assert datasets.create_calls[0]["name"] == "travel-planner-golden-v2"
    assert {call["experiment_name"] for call in wrapper._client.experiments.calls} == {
        "golden-baseline-v2",
        "golden-fix-v2",
    }


def test_run_golden_comparison_reuses_existing_dataset(
    tmp_config: NengokConfig,
    sample_agent_runner_registered: None,
) -> None:
    del sample_agent_runner_registered
    config = replace(tmp_config, project_identifier=SAMPLE_AGENT_PROJECT)
    wrapper = PhoenixWrapper(config)
    wrapper._client = _GoldenClient(ran=_stub_ran_experiment(), dataset_existing=True)

    wrapper.run_golden_comparison(
        baseline_prompt="BASE",
        proposed_prompt="FIX",
        evaluators=[output_is_present],
    )

    assert wrapper._client.datasets.create_calls == []


def test_run_golden_comparison_caches_loaded_json(
    tmp_config: NengokConfig,
    sample_agent_runner_registered: None,
) -> None:
    del sample_agent_runner_registered
    config = replace(tmp_config, project_identifier=SAMPLE_AGENT_PROJECT)
    wrapper = PhoenixWrapper(config)
    wrapper._client = _GoldenClient(ran=_stub_ran_experiment(), dataset_existing=False)

    wrapper.run_golden_comparison(
        baseline_prompt="BASE",
        proposed_prompt="FIX",
        evaluators=[output_is_present],
    )
    wrapper.run_golden_comparison(
        baseline_prompt="BASE2",
        proposed_prompt="FIX2",
        evaluators=[output_is_present],
    )

    assert len(wrapper._client.datasets.create_calls) == 1
