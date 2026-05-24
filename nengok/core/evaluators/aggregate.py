"""
Aggregate Phoenix experiment outputs into a single pass-rate.

Phoenix returns per-row evaluator scores. Nengok collapses them into one
number for the Verifier gate using this rule:

  - Every code evaluator must pass (strict AND). A code score of 1.0
    counts as a pass; anything below 1.0 fails.
  - Judge scores are averaged. The row passes when the mean reaches
    ``judge_pass_threshold`` (default 0.5).
  - A row with no evaluators at all counts as a pass; otherwise the
    row pass is ``code_pass AND judge_pass``.

The helper takes the raw Phoenix payload as plain mappings so unit
tests can build fixture data without importing the Phoenix SDK.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

DEFAULT_JUDGE_PASS_THRESHOLD = 0.5
CODE_PASS_SCORE = 1.0


@dataclass(frozen=True)
class _EvalScore:
    name: str
    score: float | None
    label: str | None
    is_code: bool


@dataclass(frozen=True)
class ExperimentSummary:
    pass_rate: float
    per_case: list[dict[str, Any]]


def summarize_experiment(
    *,
    task_runs: Sequence[Mapping[str, Any]],
    evaluation_runs: Sequence[Mapping[str, Any]],
    code_evaluator_names: Iterable[str],
    judge_pass_threshold: float = DEFAULT_JUDGE_PASS_THRESHOLD,
) -> ExperimentSummary:
    """
    Reduce one Phoenix RanExperiment into (pass_rate, per_case).

    See the module docstring for the per-row pass rule. ``task_runs`` is
    the ``task_runs`` field of ``RanExperiment``; ``evaluation_runs`` is
    the ``evaluation_runs`` field. ``code_evaluator_names`` partitions
    evaluator names into the strict-AND bucket; anything not in that set
    is treated as a judge score.
    """
    code_names = set(code_evaluator_names)
    by_run: dict[str, list[_EvalScore]] = {}
    for evaluation in evaluation_runs:
        run_id = str(evaluation.get("experiment_run_id", ""))
        if not run_id:
            continue
        name = str(evaluation.get("name", ""))
        for score in _flatten_evaluation_result(evaluation.get("result"), default_name=name):
            tagged = _EvalScore(
                name=score.name,
                score=score.score,
                label=score.label,
                is_code=score.name in code_names,
            )
            by_run.setdefault(run_id, []).append(tagged)

    per_case: list[dict[str, Any]] = []
    passes = 0

    for task in task_runs:
        run_id = str(task.get("id", ""))
        scores = by_run.get(run_id, [])
        code_scores = [s for s in scores if s.is_code]
        judge_scores = [s for s in scores if not s.is_code]

        code_pass = _all_code_pass(code_scores)
        judge_avg = _judge_average(judge_scores)
        judge_pass = judge_avg is None or judge_avg >= judge_pass_threshold
        row_pass = code_pass and judge_pass

        if row_pass:
            passes += 1

        per_case.append(
            {
                "task_run_id": run_id,
                "dataset_example_id": task.get("dataset_example_id"),
                "output": task.get("output"),
                "error": task.get("error"),
                "code_scores": {s.name: s.score for s in code_scores},
                "judge_scores": {s.name: s.score for s in judge_scores},
                "judge_average": judge_avg,
                "passed": row_pass,
            }
        )

    total = len(task_runs)
    pass_rate = (passes / total) if total else 0.0
    return ExperimentSummary(pass_rate=pass_rate, per_case=per_case)


def _flatten_evaluation_result(
    result: Any,
    *,
    default_name: str,
) -> list[_EvalScore]:
    """Normalize the heterogeneous ``result`` field into flat _EvalScore rows."""
    if result is None:
        return []
    if isinstance(result, Mapping):
        return [_score_from_mapping(result, default_name=default_name)]
    if isinstance(result, Sequence) and not isinstance(result, str | bytes):
        return [
            _score_from_mapping(item, default_name=default_name)
            for item in result
            if isinstance(item, Mapping)
        ]
    return []


def _score_from_mapping(mapping: Mapping[str, Any], *, default_name: str) -> _EvalScore:
    raw_score = mapping.get("score")
    score = float(raw_score) if isinstance(raw_score, int | float) else None
    label_value = mapping.get("label")
    label = str(label_value) if label_value is not None else None
    name = str(mapping.get("name") or default_name)
    return _EvalScore(name=name, score=score, label=label, is_code=False)


def _all_code_pass(scores: list[_EvalScore]) -> bool:
    if not scores:
        return True
    return all(s.score is not None and s.score >= CODE_PASS_SCORE for s in scores)


def _judge_average(scores: list[_EvalScore]) -> float | None:
    numeric = [s.score for s in scores if s.score is not None]
    if not numeric:
        return None
    return sum(numeric) / len(numeric)
