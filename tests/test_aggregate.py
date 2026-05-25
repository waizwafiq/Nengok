"""Pass-rate aggregator tests."""

from __future__ import annotations

from typing import Any

from nengok.core.evaluators.aggregate import summarize_experiment


def _task(run_id: str, *, output: Any = None) -> dict[str, Any]:
    return {
        "id": run_id,
        "dataset_example_id": f"ex-{run_id}",
        "output": output,
        "error": None,
    }


def _eval(run_id: str, name: str, score: float, *, label: str | None = None) -> dict[str, Any]:
    return {
        "experiment_run_id": run_id,
        "name": name,
        "result": {"name": name, "score": score, "label": label},
    }


CODE_NAMES = {"output_is_present", "output_is_valid_json"}


def test_all_passes_when_every_code_eval_is_one_and_no_judges() -> None:
    task_runs = [_task("r1"), _task("r2")]
    evaluations = [
        _eval("r1", "output_is_present", 1.0),
        _eval("r1", "output_is_valid_json", 1.0),
        _eval("r2", "output_is_present", 1.0),
        _eval("r2", "output_is_valid_json", 1.0),
    ]

    summary = summarize_experiment(
        task_runs=task_runs,
        evaluation_runs=evaluations,
        code_evaluator_names=CODE_NAMES,
    )

    assert summary.pass_rate == 1.0
    assert all(row["passed"] for row in summary.per_case)


def test_failing_code_eval_drops_that_row() -> None:
    task_runs = [_task("r1"), _task("r2")]
    evaluations = [
        _eval("r1", "output_is_present", 1.0),
        _eval("r1", "output_is_valid_json", 0.0),
        _eval("r2", "output_is_present", 1.0),
        _eval("r2", "output_is_valid_json", 1.0),
    ]

    summary = summarize_experiment(
        task_runs=task_runs,
        evaluation_runs=evaluations,
        code_evaluator_names=CODE_NAMES,
    )

    assert summary.pass_rate == 0.5
    failed_row = next(row for row in summary.per_case if row["task_run_id"] == "r1")
    assert failed_row["passed"] is False


def test_judge_scores_are_averaged_and_thresholded() -> None:
    task_runs = [_task("r1")]
    evaluations = [
        _eval("r1", "output_is_present", 1.0),
        _eval("r1", "output_is_valid_json", 1.0),
        _eval("r1", "coherence", 0.8),
        _eval("r1", "intent_match", 0.4),
    ]

    summary = summarize_experiment(
        task_runs=task_runs,
        evaluation_runs=evaluations,
        code_evaluator_names=CODE_NAMES,
    )

    assert summary.pass_rate == 1.0
    row = summary.per_case[0]
    assert row["judge_average"] == (0.8 + 0.4) / 2
    assert row["judge_scores"] == {"coherence": 0.8, "intent_match": 0.4}


def test_judge_average_below_threshold_fails_row() -> None:
    task_runs = [_task("r1")]
    evaluations = [
        _eval("r1", "output_is_present", 1.0),
        _eval("r1", "output_is_valid_json", 1.0),
        _eval("r1", "coherence", 0.1),
        _eval("r1", "intent_match", 0.0),
    ]

    summary = summarize_experiment(
        task_runs=task_runs,
        evaluation_runs=evaluations,
        code_evaluator_names=CODE_NAMES,
    )

    assert summary.pass_rate == 0.0
    assert summary.per_case[0]["passed"] is False


def test_task_with_no_evaluations_counts_as_pass() -> None:
    summary = summarize_experiment(
        task_runs=[_task("r1")],
        evaluation_runs=[],
        code_evaluator_names=CODE_NAMES,
    )

    assert summary.pass_rate == 1.0
    assert summary.per_case[0]["passed"] is True


def test_empty_task_runs_returns_zero_pass_rate() -> None:
    summary = summarize_experiment(
        task_runs=[],
        evaluation_runs=[],
        code_evaluator_names=CODE_NAMES,
    )

    assert summary.pass_rate == 0.0
    assert summary.per_case == []


def test_result_field_can_be_a_sequence_of_scores() -> None:
    task_runs = [_task("r1")]
    evaluations = [
        {
            "experiment_run_id": "r1",
            "name": "code_bundle",
            "result": [
                {"name": "output_is_present", "score": 1.0},
                {"name": "output_is_valid_json", "score": 1.0},
            ],
        }
    ]

    summary = summarize_experiment(
        task_runs=task_runs,
        evaluation_runs=evaluations,
        code_evaluator_names=CODE_NAMES,
    )

    assert summary.pass_rate == 1.0
    assert set(summary.per_case[0]["code_scores"]) == CODE_NAMES
