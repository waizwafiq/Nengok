"""
Confirm the configured agent runner can be imported.

Doctor only verifies that the dotted path resolves to a callable. The
runner's behavior under live traffic stays out of scope; that is the
job of the experiment loop. Treating "no agent_runner configured" as
OK matches the wizard, which leaves the field commented out for the
bundled Travel Planner demo.
"""

from __future__ import annotations

import importlib
from typing import Any

from nengok.config import NengokConfig
from nengok.diagnostics.base import ProbeResult, ProbeStatus
from nengok.runners import get_runner

PROBE_NAME = "agent-runner"


def probe_agent_runner(config: NengokConfig) -> ProbeResult:
    dotted = config.agent_runner
    if not dotted:
        runner = get_runner(config.project_identifier)
        if runner is None:
            return ProbeResult(
                name=PROBE_NAME,
                status=ProbeStatus.WARN,
                detail=(
                    f"no agent_runner configured and none registered for " f"'{config.project_identifier}'"
                ),
                fix_hint=(
                    "Set agent_runner in ~/.nengok/config.toml or call "
                    "`nengok.runners.register_runner` at import time."
                ),
            )
        return ProbeResult(
            name=PROBE_NAME,
            status=ProbeStatus.OK,
            detail=f"using registered runner for '{config.project_identifier}'",
        )

    if dotted.count(":") != 1:
        return ProbeResult(
            name=PROBE_NAME,
            status=ProbeStatus.FAIL,
            detail=f"agent_runner '{dotted}' is malformed",
            fix_hint="Expected `module.path:ClassName` (single colon).",
        )

    module_part, attr_part = dotted.split(":", 1)
    try:
        module = importlib.import_module(module_part)
    except ImportError as exc:
        return ProbeResult(
            name=PROBE_NAME,
            status=ProbeStatus.FAIL,
            detail=f"could not import '{module_part}': {exc}",
            fix_hint="Add the module to PYTHONPATH or install the package that provides it.",
        )
    target: Any = getattr(module, attr_part, None)
    if target is None:
        return ProbeResult(
            name=PROBE_NAME,
            status=ProbeStatus.FAIL,
            detail=f"'{module_part}' has no attribute '{attr_part}'",
            fix_hint="Check the dotted path against the module's actual exports.",
        )
    if not callable(target):
        return ProbeResult(
            name=PROBE_NAME,
            status=ProbeStatus.FAIL,
            detail=f"'{dotted}' resolved to a non-callable {type(target).__name__}",
            fix_hint="The runner must be a callable taking (input_dict, prompt).",
        )
    return ProbeResult(
        name=PROBE_NAME,
        status=ProbeStatus.OK,
        detail=f"{dotted} (loadable)",
    )
