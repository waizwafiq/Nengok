"""
Pluggable baseline-prompt loaders.

The Fixer needs the agent's active prompt to propose a diff against.
Different teams keep that prompt in different places: a file in the
agent's package, Phoenix prompt management, a private secrets store.
The :class:`BaselinePromptLoader` Protocol lets each source live behind
a uniform ``load(project_name)`` call so :class:`PromptProposer` does
not have to know where the bytes came from.

The bundled :func:`default_loader` factory mirrors the historical
fallback chain: the bundled file ships with the sample agent, Phoenix
prompt management wins for projects that register their prompt there,
and a config-set ``baseline_prompt_path`` is the final fallback. Users
who keep their prompt somewhere else point ``baseline_prompt_loader``
at their own factory.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from nengok.errors import BaselinePromptError

if TYPE_CHECKING:
    from nengok.config import NengokConfig
    from nengok.phoenix.client import PhoenixWrapper

SAMPLE_AGENT_PROJECT = "travel-planner-agent"
SAMPLE_AGENT_PROMPT_PATH = (
    Path(__file__).resolve().parents[3] / "sample_agent" / "prompts" / "travel_planner.md"
)


@runtime_checkable
class BaselinePromptLoader(Protocol):
    """Read the baseline prompt for one project, or return ``None``."""

    def load(self, project_name: str) -> str | None: ...


@dataclass
class FileLoader:
    """Read a baseline prompt from a fixed path on disk."""

    path: Path

    def load(self, project_name: str) -> str | None:
        if not self.path.exists():
            return None
        text = self.path.read_text(encoding="utf-8")
        return text or None


@dataclass
class PhoenixPromptLoader:
    """Read the latest prompt version from Phoenix prompt management."""

    client: PhoenixWrapper

    def load(self, project_name: str) -> str | None:
        return self.client.get_prompt_version(name=project_name)


@dataclass
class BundledSampleAgentLoader:
    """
    Read the Travel Planner's bundled prompt when the active project matches.

    Lets the demo cycle work without forcing the user to set
    ``baseline_prompt_path`` in their config. Returns ``None`` for any
    other project so the next loader in the composite gets a turn.
    """

    project_name: str = SAMPLE_AGENT_PROJECT
    path: Path = SAMPLE_AGENT_PROMPT_PATH

    def load(self, project_name: str) -> str | None:
        if project_name != self.project_name:
            return None
        if not self.path.exists():
            return None
        return self.path.read_text(encoding="utf-8") or None


@dataclass
class CompositeLoader:
    """Try each loader in order and return the first non-empty result."""

    loaders: Sequence[BaselinePromptLoader]

    def load(self, project_name: str) -> str | None:
        for loader in self.loaders:
            value = loader.load(project_name)
            if value:
                return value
        return None


def default_loader(config: NengokConfig, phoenix: PhoenixWrapper | None) -> BaselinePromptLoader:
    """Build the composite loader that matches today's fallback chain."""
    loaders: list[BaselinePromptLoader] = [BundledSampleAgentLoader()]
    if phoenix is not None:
        loaders.append(PhoenixPromptLoader(phoenix))
    if config.baseline_prompt_path is not None:
        loaders.append(FileLoader(config.baseline_prompt_path))
    return CompositeLoader(loaders)


def load_baseline_prompt_loader(
    spec: str,
    *,
    config: NengokConfig,
    phoenix: PhoenixWrapper | None,
) -> BaselinePromptLoader:
    """
    Resolve a ``module.path:factory`` spec into a configured loader.

    The factory function must accept ``(config, phoenix)`` and return
    something satisfying :class:`BaselinePromptLoader`. The default
    spec points at :func:`default_loader` so unconfigured installs get
    the historical behavior.
    """
    module_part, _, factory_part = spec.partition(":")
    if not module_part or not factory_part or ":" in factory_part:
        raise BaselinePromptError(
            f"baseline_prompt_loader spec '{spec}' is malformed. "
            "Expected `module.path:factory` (for example, "
            "`nengok.core.fixer.loaders:default_loader`).",
            project_identifier=spec,
        )

    try:
        module = import_module(module_part)
    except ImportError as exc:
        raise BaselinePromptError(
            f"Could not import module `{module_part}` referenced by "
            f"baseline_prompt_loader spec '{spec}'. Confirm it is on PYTHONPATH. "
            "Underlying error: " + str(exc),
            project_identifier=spec,
        ) from exc

    try:
        factory = getattr(module, factory_part)
    except AttributeError as exc:
        raise BaselinePromptError(
            f"Module `{module_part}` does not define `{factory_part}` "
            f"(referenced by baseline_prompt_loader spec '{spec}').",
            project_identifier=spec,
        ) from exc

    loader = factory(config, phoenix)
    if not isinstance(loader, BaselinePromptLoader):
        raise BaselinePromptError(
            f"`{factory_part}` returned {type(loader).__name__!r}, which does not "
            "satisfy BaselinePromptLoader. Implement `load(project_name: str) -> str | None`.",
            project_identifier=spec,
        )
    return loader
