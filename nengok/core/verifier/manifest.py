"""Artifact bundle manifest: writer and schema-version asserter.

Every cluster artifact directory gets a manifest.json written last, after
all artifact files are flushed. Readers call assert_manifest_version()
before touching any artifact field so schema drift is caught early and
old bundles remain parseable.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

CURRENT_SCHEMA_VERSION = 1


class ManifestVersionError(Exception):
    """Raised when a manifest schema version is unsupported or absent."""


def write_manifest(cluster_dir: Path, *, cluster_id: str, artifact_paths: list[Path]) -> Path:
    """Write manifest.json to cluster_dir after all artifact files are flushed."""
    files = [{"name": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in artifact_paths]
    manifest = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "cluster_id": cluster_id,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "files": files,
    }
    manifest_path = cluster_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def assert_manifest_version(cluster_dir: Path, *, supported: list[int] | None = None) -> dict:
    """Load and validate manifest.json from cluster_dir.

    Missing manifests are treated as legacy/unversioned bundles — never
    assumed to be version 1. Raises ManifestVersionError on missing or
    unsupported schema versions.
    """
    if supported is None:
        supported = [CURRENT_SCHEMA_VERSION]

    manifest_path = cluster_dir / "manifest.json"
    if not manifest_path.exists():
        raise ManifestVersionError(
            f"No manifest.json in {cluster_dir}. "
            "Bundle predates schema versioning and cannot be read by this reader. "
            "Re-run the Nengok cycle to regenerate artifacts with a versioned manifest."
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ManifestVersionError(
            f"manifest.json at {cluster_dir} is not a JSON object. "
            "Re-run the Nengok cycle to regenerate artifacts with a versioned manifest."
        )
    version = manifest.get("schema_version")
    if version not in supported:
        raise ManifestVersionError(
            f"Artifact bundle at {cluster_dir} has schema_version={version!r}, "
            f"but this reader supports only {supported}. "
            "Upgrade Nengok or regenerate the artifact bundle."
        )
    return manifest
