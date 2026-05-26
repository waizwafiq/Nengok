"""
Report on the configured baseline prompt file.

The prompt path is optional: when it is unset, the Fixer falls back to
the prompt stored in Phoenix or to the bundled sample. The probe
reports OK in both the "configured + readable" and "unset" cases, and
FAIL when the path is configured but unreadable. `NengokConfig.validate`
already rejects nonexistent paths at load time, so a configured-but-
missing file should never reach the probe in practice; the check
remains for defensive symmetry with the agent-runner probe.
"""

from __future__ import annotations

import os

from nengok.config import NengokConfig
from nengok.diagnostics.base import ProbeResult, ProbeStatus

PROBE_NAME = "baseline-prompt"


def probe_baseline_prompt(config: NengokConfig) -> ProbeResult:
    path = config.baseline_prompt_path
    if path is None:
        return ProbeResult(
            name=PROBE_NAME,
            status=ProbeStatus.OK,
            detail="not configured (Fixer will use the Phoenix-stored prompt)",
        )

    if not path.exists():
        return ProbeResult(
            name=PROBE_NAME,
            status=ProbeStatus.FAIL,
            detail=f"{path} does not exist",
            fix_hint="Point baseline_prompt_path at a readable .md or .txt file, or unset it.",
        )
    if not path.is_file():
        return ProbeResult(
            name=PROBE_NAME,
            status=ProbeStatus.FAIL,
            detail=f"{path} is not a regular file",
            fix_hint="baseline_prompt_path should be a single text file, not a directory.",
        )
    if not os.access(path, os.R_OK):
        return ProbeResult(
            name=PROBE_NAME,
            status=ProbeStatus.FAIL,
            detail=f"{path} is not readable by the current user",
            fix_hint=f"chmod a+r {path}",
        )

    size_kb = path.stat().st_size / 1024
    return ProbeResult(
        name=PROBE_NAME,
        status=ProbeStatus.OK,
        detail=f"{path} ({size_kb:.1f} KB)",
    )
