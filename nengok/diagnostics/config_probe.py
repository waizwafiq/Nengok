"""
Confirm that `~/.nengok/config.toml` is present and readable.

`nengok doctor` runs after `NengokConfig.load`, so a missing file
already manifests as a hard error before this probe fires. The probe
exists so the report shows the resolved path and a freshness hint,
which makes "I edited the wrong file" mistakes obvious.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

from nengok.config import DEFAULT_CONFIG_PATH, NengokConfig
from nengok.diagnostics.base import ProbeResult, ProbeStatus


def probe_config_file(_config: NengokConfig) -> ProbeResult:
    path = DEFAULT_CONFIG_PATH
    if not path.exists():
        return ProbeResult(
            name="config",
            status=ProbeStatus.FAIL,
            detail=f"{path} does not exist",
            fix_hint="Run `nengok init` to create one, or pass --config-path explicitly.",
        )
    if not os.access(path, os.R_OK):
        return ProbeResult(
            name="config",
            status=ProbeStatus.FAIL,
            detail=f"{path} is not readable by the current user",
            fix_hint=f"chmod a+r {path} or rerun `nengok init`.",
        )
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).date().isoformat()
    return ProbeResult(
        name="config",
        status=ProbeStatus.OK,
        detail=f"{path} (last modified {modified})",
    )
