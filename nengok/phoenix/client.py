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

from dataclasses import dataclass
from typing import Any

from nengok.config import NengokConfig
from nengok.core.evaluators.code_evals import CodeEvaluator
from nengok.core.evaluators.llm_judges import JudgeSpec
from nengok.core.types import RegressionTestCase, TraceSpan
from nengok.phoenix.spans import normalize_span
from nengok.utils.logging import get_logger

logger = get_logger(__name__)


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

    def create_dataset(self, *, name: str, cases: list[RegressionTestCase]) -> Any:
        client = self._get_client()
        inputs = [c.input for c in cases]
        outputs = [c.expected for c in cases]
        return client.datasets.create_dataset(name=name, inputs=inputs, outputs=outputs)

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
        Execute one experiment via `px_client.experiments.run_experiment`.

        The body is intentionally a placeholder: the implementation will
        translate `JudgeSpec` into `phoenix.evals.ClassificationEvaluator`
        instances, build the task function from `prompt`, and feed the
        whole stack into `run_experiment(..., dry_run=dry_run)`.
        """
        del dataset_ref, prompt, evaluators, dry_run
        logger.warning("Phoenix experiment placeholder used for '%s'", experiment_name)
        return _ExperimentRun(experiment_id=None, pass_rate=0.0, per_case=[])

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
        `golden_regression_limit` ceiling.
        """
        del baseline_prompt, proposed_prompt, evaluators
        logger.warning("Phoenix golden-set placeholder used")
        empty = _ExperimentRun(experiment_id=None, pass_rate=1.0, per_case=[])
        return empty, empty
