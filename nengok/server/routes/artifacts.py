"""
Read-only artifact endpoints.

The dashboard renders the proposed prompt, the regression dataset, and
the RCA document for every fix-proposed cluster. The artifacts live on
disk under `config.artifacts_dir / <cluster_id>/`.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from nengok.server.dependencies import ConfigDep

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


@router.get("/{cluster_id}")
def get_artifacts(cluster_id: str, config: ConfigDep) -> dict:
    cluster_dir: Path = config.artifacts_dir / cluster_id
    if not cluster_dir.exists():
        raise HTTPException(status_code=404, detail="No artifacts for this cluster yet")

    return {
        "cluster_id": cluster_id,
        "prompt": _read_optional(cluster_dir / "prompt.md"),
        "regression": _read_optional(cluster_dir / "regression.json"),
        "rca": _read_optional(cluster_dir / "rca.md"),
    }


def _read_optional(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.exists() else None
