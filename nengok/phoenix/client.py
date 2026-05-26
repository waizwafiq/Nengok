"""
The Nengok-facing wrapper around the Phoenix Python SDK.

Every Phoenix interaction in the loop flows through here. Centralizing
the SDK calls in one module:

  - Lets us keep `arize-phoenix-client` an optional import so the
    package installs even when Phoenix isn't reachable yet.
  - Gives us one place to enforce the project rule "Phoenix SDK for
    writes, MCP for reads."
  - Makes the orchestrator trivially fakeable for unit tests.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nengok.config import NengokConfig
from nengok.core.evaluators.aggregate import summarize_experiment
from nengok.core.evaluators.code_evals import CodeEvaluator
from nengok.core.evaluators.llm_judges import JudgeSpec, _ensure_phoenix_judge
from nengok.core.types import RegressionTestCase, TraceSpan
from nengok.phoenix.spans import normalize_span
from nengok.runners.agent_runner import AgentRunner, get_runner
from nengok.utils.logging import get_logger

logger = get_logger(__name__)

SAMPLE_GOLDEN_PATH = Path(__file__).resolve().parents[2] / "golden_dataset" / "travel_planner_golden.json"


@dataclass
class _ExperimentRun:
    experiment_id: str | None
    pass_rate: float
    per_case: list[dict[str, Any]]


class PhoenixWrapper:
    """Lightweight facade over `phoenix.client.Client`."""

    def __init__(self, config: NengokConfig) -> None:
        self._config = config
        self._client: Any | None = None
        self._golden_cache: dict[str, Any] | None = None
        self._golden_dataset_ref: Any | None = None

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from phoenix.client import Client
        except ImportError as exc:  # pragma: no cover - import guard
            raise RuntimeError(
                "arize-phoenix-client is not installed. "
                "Install it via `pip install nengok[phoenix]` or `pip install arize-phoenix-client`."
            ) from exc

        kwargs: dict[str, Any] = {"base_url": self._config.phoenix_base_url}
        if self._config.phoenix_api_key:
            kwargs["api_key"] = self._config.phoenix_api_key
        self._client = Client(**kwargs)
        return self._client

    def get_spans(self, *, project_identifier: str, limit: int) -> list[TraceSpan]:
        client = self._get_client()
        raw = client.spans.get_spans(project_identifier=project_identifier, limit=limit)
        return [normalize_span(item) for item in raw]

    def get_spans_by_ids(
        self,
        *,
        project_identifier: str,
        span_ids: Sequence[str],
        limit: int = 1000,
    ) -> list[TraceSpan]:
        """
        Return only the spans in `span_ids` from the given project.

        The Phoenix client's ``get_spans`` does not support a span-id filter
        (only trace-id), so this helper pulls a bounded batch from the
        project and filters client-side. Caller picks ``limit`` to bound
        the worst case.
        """
        if not span_ids:
            return []
        wanted = set(span_ids)
        batch = self.get_spans(project_identifier=project_identifier, limit=limit)
        return [s for s in batch if s.span_id in wanted]

    def get_prompt_version(self, *, name: str) -> str | None:
        """
        Return the latest prompt template for ``name`` from Phoenix.

        Falls back to ``None`` when Phoenix does not have a prompt by
        that identifier so callers can apply their own fallback (a
        bundled file or ``config.baseline_prompt_path``).
        """
        client = self._get_client()
        try:
            version = client.prompts.get(prompt_identifier=name)
        except ValueError:
            return None
        template = getattr(version, "template", None)
        if template is None:
            return None
        return str(template)

    def create_dataset(self, *, name: str, cases: list[RegressionTestCase]) -> Any:
        client = self._get_client()
        inputs = [c.input for c in cases]
        outputs = [c.expected for c in cases]
        return client.datasets.create_dataset(name=name, inputs=inputs, outputs=outputs)

    def get_dataset(self, *, name: str) -> Any | None:
        """
        Look up a Phoenix dataset by name.

        Returns ``None`` when the dataset does not exist so callers can
        idempotently create one without catching the SDK's lookup
        exception themselves.
        """
        client = self._get_client()
        try:
            return client.datasets.get_dataset(dataset=name)
        except ValueError:
            return None

    def attach_evaluators(
        self,
        *,
        experiment_id: str,
        evaluators: list[CodeEvaluator | JudgeSpec],
    ) -> Any:
        """
        Add evaluators to an existing experiment without re-running the task.

        The dashboard uses this when an operator wants to score an old
        experiment against a newly added judge. Phoenix exposes it as
        ``evaluate_experiment``; the Nengok name makes intent obvious
        at the call site.
        """
        client = self._get_client()
        experiment = client.experiments.get_experiment(experiment_id=experiment_id)
        resolved = _resolve_evaluators(evaluators)
        return client.experiments.evaluate_experiment(
            experiment=experiment,
            evaluators=resolved,
        )

    def run_experiment(
        self,
        *,
        dataset_ref: Any,
        prompt: str,
        evaluators: list[CodeEvaluator | JudgeSpec],
        experiment_name: str,
        dry_run: int,
    ) -> _ExperimentRun:
        """
        Execute one Phoenix experiment and return the aggregated pass rate.

        The task callable runs the monitored agent against each dataset
        row with ``prompt`` injected, so a fix candidate can be A/B'd
        against the baseline without touching the agent's bundled prompt.
        """
        runner = get_runner(self._config.project_identifier)
        if runner is None:
            raise RuntimeError(
                f"No agent runner registered for project "
                f"'{self._config.project_identifier}'. Call "
                "`nengok.runners.register_runner` before running an experiment."
            )

        client = self._get_client()
        resolved, code_names = _resolve_evaluators_with_names(evaluators)
        task = _build_task(prompt=prompt, runner=runner)

        ran = client.experiments.run_experiment(
            dataset=dataset_ref,
            task=task,
            evaluators=resolved,
            experiment_name=experiment_name,
            dry_run=dry_run,
            print_summary=False,
        )

        summary = summarize_experiment(
            task_runs=ran.get("task_runs") or [],
            evaluation_runs=_normalize_evaluation_runs(ran.get("evaluation_runs") or []),
            code_evaluator_names=code_names,
        )
        return _ExperimentRun(
            experiment_id=ran.get("experiment_id"),
            pass_rate=summary.pass_rate,
            per_case=summary.per_case,
        )

    def run_golden_comparison(
        self,
        *,
        baseline_prompt: str,
        proposed_prompt: str,
        evaluators: list[CodeEvaluator | JudgeSpec],
    ) -> tuple[_ExperimentRun, _ExperimentRun]:
        """
        Run both prompt versions against the curated golden dataset.

        The Verifier uses the result delta to enforce the
        ``golden_regression_limit`` ceiling. The golden JSON is loaded
        once per wrapper instance and the Phoenix dataset is created
        idempotently so repeated cycles do not stack duplicate copies.
        """
        golden = self._load_golden_dataset()
        dataset_ref = self._ensure_golden_dataset(golden)
        version = golden.get("version", 1)

        baseline_run = self.run_experiment(
            dataset_ref=dataset_ref,
            prompt=baseline_prompt,
            evaluators=evaluators,
            experiment_name=f"golden-baseline-v{version}",
            dry_run=0,
        )
        fix_run = self.run_experiment(
            dataset_ref=dataset_ref,
            prompt=proposed_prompt,
            evaluators=evaluators,
            experiment_name=f"golden-fix-v{version}",
            dry_run=0,
        )
        return baseline_run, fix_run

    def _load_golden_dataset(self) -> dict[str, Any]:
        if self._golden_cache is not None:
            return self._golden_cache
        if not SAMPLE_GOLDEN_PATH.exists():
            raise RuntimeError(
                f"Golden dataset not found at {SAMPLE_GOLDEN_PATH}. "
                "Bundle a golden_dataset/ directory with the SDK or override "
                "the path before calling run_golden_comparison."
            )
        parsed: dict[str, Any] = json.loads(SAMPLE_GOLDEN_PATH.read_text(encoding="utf-8"))
        self._golden_cache = parsed
        return parsed

    def _ensure_golden_dataset(self, golden: dict[str, Any]) -> Any:
        if self._golden_dataset_ref is not None:
            return self._golden_dataset_ref
        version = golden.get("version", 1)
        dataset_name = f"travel-planner-golden-v{version}"
        existing = self.get_dataset(name=dataset_name)
        if existing is not None:
            self._golden_dataset_ref = existing
            return existing
        cases = [
            RegressionTestCase(
                case_id=case["case_id"],
                input=case["input"],
                expected=case["expected"],
                metadata=case.get("metadata", {}),
            )
            for case in golden["cases"]
        ]
        created = self.create_dataset(name=dataset_name, cases=cases)
        self._golden_dataset_ref = created
        return created


_EVALUATION_RUN_FIELDS = ("experiment_run_id", "name", "result", "error")


def _normalize_evaluation_runs(runs: Sequence[Any]) -> list[Mapping[str, Any]]:
    """
    Coerce Phoenix `ExperimentEvaluationRun` objects into plain dicts.

    Phoenix returns `task_runs` as `ExperimentRun` (TypedDict) but
    `evaluation_runs` as a frozen dataclass with attribute access. The
    aggregator in `nengok.core.evaluators.aggregate` takes the dict
    shape, so we adapt here and keep the aggregator SDK-agnostic.
    """
    normalized: list[Mapping[str, Any]] = []
    for run in runs:
        if isinstance(run, Mapping):
            normalized.append(run)
            continue
        normalized.append({field: getattr(run, field, None) for field in _EVALUATION_RUN_FIELDS})
    return normalized


def _resolve_evaluators(evaluators: list[CodeEvaluator | JudgeSpec]) -> list[Any]:
    """Turn the Nengok evaluator union into the heterogeneous list Phoenix wants."""
    resolved, _ = _resolve_evaluators_with_names(evaluators)
    return resolved


def _resolve_evaluators_with_names(
    evaluators: list[CodeEvaluator | JudgeSpec],
) -> tuple[list[Any], set[str]]:
    """Same as ``_resolve_evaluators`` but also returns the code evaluator names.

    Phoenix scores evaluators by name, so the aggregator needs to know
    which names are code (strict-AND) versus which are judge (averaged).
    """
    resolved: list[Any] = []
    code_names: set[str] = set()
    for evaluator in evaluators:
        if isinstance(evaluator, JudgeSpec):
            resolved.append(_ensure_phoenix_judge(evaluator))
        else:
            resolved.append(evaluator)
            code_names.add(getattr(evaluator, "__name__", repr(evaluator)))
    return resolved, code_names


def _build_task(*, prompt: str, runner: AgentRunner) -> Callable[..., dict[str, Any]]:
    """Wrap an AgentRunner in the signature Phoenix's run_experiment calls."""

    def task(example: Mapping[str, Any]) -> dict[str, Any]:
        raw_input = example.get("input") or {}
        input_row = dict(raw_input) if isinstance(raw_input, Mapping) else {"value": raw_input}
        return runner(input_row, prompt)

    return task
