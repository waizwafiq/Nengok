"""
Generate a root-cause hypothesis for one cluster.

Per the proposal's "code-first, LLM-second" rule, this stage is one of
the few places where Gemini's reasoning is irreplaceable: the task
is to read 3-5 exemplar traces and propose what went wrong upstream.
"""

from __future__ import annotations

from dataclasses import dataclass

from nengok.config import NengokConfig
from nengok.core.types import Cluster, RootCauseHypothesis
from nengok.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class Hypothesizer:
    config: NengokConfig

    def hypothesize(self, cluster: Cluster) -> RootCauseHypothesis:
        """Return a structured root-cause hypothesis."""
        return self._call_gemini_diagnoser(cluster)

    def _call_gemini_diagnoser(self, cluster: Cluster) -> RootCauseHypothesis:
        """
        Placeholder Gemini call.

        The implementation will:
          1. Look up each `exemplar_span_id` via the Phoenix wrapper.
          2. Build a structured prompt that includes the active agent
             prompt version, the exemplar inputs/outputs, and the
             observed anomaly signals.
          3. Parse Gemini's JSON response into RootCauseHypothesis.
        """
        logger.debug("Hypothesizer placeholder for cluster=%s", cluster.cluster_id)
        return RootCauseHypothesis(
            summary=f"Pending diagnosis for cluster '{cluster.name}'.",
            expected_behavior="Agent should return a valid response that matches the user's intent.",
            actual_behavior="Agent returns subtly wrong or incomplete output without raising an error.",
            likely_cause="Unknown — requires Gemini diagnoser pass.",
            implicated_tools=[],
        )
