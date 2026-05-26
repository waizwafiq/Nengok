"""
Confirm the configured Phoenix project exists and has recent traffic.

The probe pulls the most recent spans via the Phoenix Python client.
An empty project is reported as a warning rather than a hard failure
because a freshly created project that has not received traces is a
valid state. A missing project (the wrapper raises) is a FAIL with a
copy-paste hint pointing at `sample_agent.seed`.
"""

from __future__ import annotations

from typing import Any

from nengok.config import NengokConfig
from nengok.diagnostics.base import ProbeResult, ProbeStatus

PROBE_NAME = "phoenix-project"
_SAMPLE_LIMIT = 10


def probe_phoenix_project(
    config: NengokConfig,
    *,
    wrapper_factory: Any | None = None,
) -> ProbeResult:
    """
    Sample spans from the configured project.

    `wrapper_factory` is injectable so tests can supply a stub instead
    of constructing the real Phoenix wrapper (which requires
    `arize-phoenix-client`).
    """
    factory = wrapper_factory or _default_wrapper_factory
    project = config.project_identifier
    try:
        wrapper = factory(config)
        spans = wrapper.get_spans(project_identifier=project, limit=_SAMPLE_LIMIT)
    except RuntimeError as exc:
        return ProbeResult(
            name=PROBE_NAME,
            status=ProbeStatus.FAIL,
            detail=f"could not query project '{project}': {exc}",
            fix_hint=(
                f"Confirm '{project}' exists in Phoenix and that the API key "
                "has read access. `python -m sample_agent.seed --count 5` "
                "creates the bundled sample project."
            ),
        )
    except Exception as exc:
        return ProbeResult(
            name=PROBE_NAME,
            status=ProbeStatus.FAIL,
            detail=f"Phoenix client raised {exc.__class__.__name__}: {exc}",
            fix_hint="Re-run with -v for the full traceback.",
        )

    count = len(spans)
    if count == 0:
        return ProbeResult(
            name=PROBE_NAME,
            status=ProbeStatus.WARN,
            detail=f"project '{project}' exists but has no spans yet",
            fix_hint=(
                "Run `python -m sample_agent.seed --count 5` (or point your own "
                "agent at this project) so the Observer has data to read."
            ),
        )
    return ProbeResult(
        name=PROBE_NAME,
        status=ProbeStatus.OK,
        detail=f"project '{project}' has at least {count} recent spans",
    )


def _default_wrapper_factory(config: NengokConfig) -> Any:
    from nengok.phoenix.client import PhoenixWrapper

    return PhoenixWrapper(config=config)
