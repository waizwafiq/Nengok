"""
Load an :class:`~nengok.runners.protocol.AgentRunner` from a dotted-path spec.

The spec is ``module.path:ClassName``. The class is instantiated with
``kwargs``, and the resulting instance is verified against the
:class:`AgentRunner` Protocol at runtime so a misconfigured runner
fails before the first Phoenix experiment fires.

The loader is the canonical way Nengok turns a config string into a
runnable instance. The legacy
:func:`nengok.runners.agent_runner.register_runner` API stays available
for bootstrap modules that prefer imperative registration.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from nengok.errors import AgentRunnerLoadError
from nengok.runners.protocol import AgentRunner


def load_runner(spec: str, kwargs: dict[str, Any] | None = None) -> AgentRunner:
    """Import and instantiate the runner referenced by ``spec``."""
    module_part, _, class_part = spec.partition(":")
    if not module_part or not class_part or ":" in class_part:
        raise AgentRunnerLoadError(
            f"agent_runner spec '{spec}' is malformed. "
            "Expected `module.path:ClassName` (for example, "
            "`nengok.runners.sample_agent_runner:SampleAgentRunner`).",
            project_identifier=spec,
        )

    try:
        module = import_module(module_part)
    except ImportError as exc:
        raise AgentRunnerLoadError(
            f"Could not import module `{module_part}` referenced by "
            f"agent_runner spec '{spec}'. Confirm the module is on PYTHONPATH "
            "and that the package providing it is installed in the same venv "
            "as Nengok. Underlying error: " + str(exc),
            project_identifier=spec,
        ) from exc

    try:
        runner_cls = getattr(module, class_part)
    except AttributeError as exc:
        raise AgentRunnerLoadError(
            f"Module `{module_part}` does not define `{class_part}` "
            f"(referenced by agent_runner spec '{spec}'). Check the class "
            "name for typos and confirm the symbol is exported.",
            project_identifier=spec,
        ) from exc

    init_kwargs = kwargs or {}
    try:
        instance = runner_cls(**init_kwargs)
    except TypeError as exc:
        raise AgentRunnerLoadError(
            f"Failed to construct `{class_part}` with kwargs {init_kwargs!r}: {exc}. "
            "Check `agent_runner_kwargs` in your config and the class's "
            "`__init__` signature.",
            project_identifier=spec,
        ) from exc

    if not isinstance(instance, AgentRunner):
        missing = _missing_protocol_members(instance)
        detail = (
            f"`{class_part}` is missing required member{'s' if len(missing) != 1 else ''} "
            f"{', '.join(missing)}."
            if missing
            else f"`{class_part}` does not satisfy the AgentRunner protocol."
        )
        raise AgentRunnerLoadError(
            f"{detail} An AgentRunner must expose a `name` property and a "
            "`run(agent_input: dict, prompt: str) -> dict` method.",
            project_identifier=spec,
        )

    return instance


def _missing_protocol_members(instance: object) -> list[str]:
    missing: list[str] = []
    if not hasattr(instance, "name"):
        missing.append("`name` property")
    run = getattr(instance, "run", None)
    if not callable(run):
        missing.append("`run(agent_input: dict, prompt: str) -> dict` method")
    return missing
