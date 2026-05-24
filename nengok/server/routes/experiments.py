"""
Experiment summary endpoints.

The dashboard reads experiment results on demand from the Phoenix
client. Because Phoenix is the system of record for experiment data,
Nengok does not duplicate it into SQLite — these routes are a thin
proxy.
"""

from __future__ import annotations

from fastapi import APIRouter

from nengok.server.dependencies import ConfigDep

router = APIRouter(prefix="/experiments", tags=["experiments"])


@router.get("/{cluster_id}/latest")
def latest_experiment(cluster_id: str, config: ConfigDep) -> dict:
    del config
    return {
        "cluster_id": cluster_id,
        "baseline_pass_rate": None,
        "fix_pass_rate": None,
        "per_case": [],
        "note": "Implementation reads from PhoenixWrapper.run_experiment results.",
    }
