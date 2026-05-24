"""
Generate regression test cases targeted at a single failure cluster.

These cases are written to Phoenix as a Dataset (by the experiment
runner) and also persisted locally to the artifacts directory after
verification.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from nengok.config import NengokConfig
from nengok.core.types import Cluster, RegressionTestCase
from nengok.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class TestGenerator:
    config: NengokConfig

    def generate(self, cluster: Cluster) -> list[RegressionTestCase]:
        """Return 5-20 RegressionTestCase rows for the given cluster."""
        cases = self._call_gemini_test_generator(cluster)
        logger.info("Generated %d regression cases for cluster '%s'", len(cases), cluster.name)
        return cases

    def _call_gemini_test_generator(self, cluster: Cluster) -> list[RegressionTestCase]:
        """
        Placeholder Gemini call.

        The implementation prompts Gemini with the cluster name, the
        root-cause hypothesis, and the exemplar trace inputs, and asks
        for a JSON list of cases that should trigger the failure.
        """
        return [
            RegressionTestCase(
                case_id=str(uuid.uuid4()),
                input={"prompt": f"Regression case for {cluster.name}"},
                expected={"contains": cluster.name},
                metadata={"cluster_id": cluster.cluster_id},
            )
        ]
