"""Tests for the pluggable baseline-prompt loader."""

from __future__ import annotations

import textwrap
from dataclasses import replace
from pathlib import Path

import pytest

from nengok.config import NengokConfig
from nengok.core.fixer.loaders import (
    SAMPLE_AGENT_PROJECT,
    BaselinePromptLoader,
    BundledSampleAgentLoader,
    CompositeLoader,
    FileLoader,
    PhoenixPromptLoader,
    default_loader,
    load_baseline_prompt_loader,
)
from nengok.errors import BaselinePromptError


class _StubPhoenix:
    def __init__(self, prompts: dict[str, str] | None = None) -> None:
        self._prompts = prompts or {}
        self.calls: list[str] = []

    def get_prompt_version(self, *, name: str) -> str | None:
        self.calls.append(name)
        return self._prompts.get(name)


def test_file_loader_returns_disk_contents(tmp_path: Path) -> None:
    path = tmp_path / "p.md"
    path.write_text("FROM-DISK", encoding="utf-8")
    assert FileLoader(path).load("any-project") == "FROM-DISK"


def test_file_loader_returns_none_when_missing(tmp_path: Path) -> None:
    assert FileLoader(tmp_path / "missing.md").load("any-project") is None


def test_file_loader_returns_none_when_empty(tmp_path: Path) -> None:
    path = tmp_path / "empty.md"
    path.write_text("", encoding="utf-8")
    assert FileLoader(path).load("any-project") is None


def test_phoenix_loader_delegates_to_client() -> None:
    phoenix = _StubPhoenix(prompts={"my-agent": "FROM-PHOENIX"})
    assert PhoenixPromptLoader(phoenix).load("my-agent") == "FROM-PHOENIX"
    assert phoenix.calls == ["my-agent"]


def test_phoenix_loader_returns_none_when_unknown() -> None:
    phoenix = _StubPhoenix(prompts={})
    assert PhoenixPromptLoader(phoenix).load("unknown-agent") is None


def test_bundled_sample_loader_only_fires_for_matching_project() -> None:
    loader = BundledSampleAgentLoader()
    assert loader.load("not-the-sample-agent") is None
    bundled = loader.load(SAMPLE_AGENT_PROJECT)
    assert bundled is not None
    assert bundled.startswith("# Travel Planner")


def test_composite_returns_first_non_empty_result() -> None:
    class _Always:
        def __init__(self, value: str | None) -> None:
            self.value = value
            self.calls: list[str] = []

        def load(self, project_name: str) -> str | None:
            self.calls.append(project_name)
            return self.value

    miss = _Always(None)
    hit = _Always("WINNER")
    skipped = _Always("NEVER-CALLED")

    composite = CompositeLoader([miss, hit, skipped])
    assert composite.load("p") == "WINNER"
    assert miss.calls == ["p"]
    assert hit.calls == ["p"]
    assert skipped.calls == []


def test_composite_returns_none_when_no_loader_matches() -> None:
    class _Miss:
        def load(self, _project_name: str) -> str | None:
            return None

    assert CompositeLoader([_Miss(), _Miss()]).load("p") is None


def test_default_loader_uses_bundled_path_for_sample_agent(tmp_config: NengokConfig) -> None:
    config = replace(tmp_config, project_identifier=SAMPLE_AGENT_PROJECT)
    phoenix = _StubPhoenix(prompts={SAMPLE_AGENT_PROJECT: "PHOENIX-WINS"})

    loader = default_loader(config, phoenix)
    resolved = loader.load(SAMPLE_AGENT_PROJECT)

    assert resolved is not None
    assert resolved.startswith("# Travel Planner")
    assert phoenix.calls == []


def test_default_loader_falls_back_to_phoenix_then_file(tmp_config: NengokConfig, tmp_path: Path) -> None:
    prompt_file = tmp_path / "fallback.md"
    prompt_file.write_text("FROM-FILE", encoding="utf-8")
    config = replace(
        tmp_config,
        project_identifier="custom-agent",
        baseline_prompt_path=prompt_file,
    )

    phoenix_hit = _StubPhoenix(prompts={"custom-agent": "FROM-PHOENIX"})
    phoenix_miss = _StubPhoenix(prompts={})

    assert default_loader(config, phoenix_hit).load("custom-agent") == "FROM-PHOENIX"
    assert default_loader(config, phoenix_miss).load("custom-agent") == "FROM-FILE"


def test_load_baseline_prompt_loader_resolves_default(tmp_config: NengokConfig) -> None:
    loader = load_baseline_prompt_loader(
        tmp_config.baseline_prompt_loader,
        config=tmp_config,
        phoenix=_StubPhoenix(),
    )
    assert isinstance(loader, BaselinePromptLoader)


def test_load_baseline_prompt_loader_imports_custom_factory(
    tmp_config: NengokConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module_path = tmp_path / "custom_loader_factory.py"
    module_path.write_text(
        textwrap.dedent(
            """
            class FixedLoader:
                def load(self, project_name: str):
                    return "FROM-CUSTOM-LOADER"


            def build(config, phoenix):
                return FixedLoader()
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    loader = load_baseline_prompt_loader(
        "custom_loader_factory:build",
        config=tmp_config,
        phoenix=None,
    )
    assert loader.load("any-project") == "FROM-CUSTOM-LOADER"


def test_load_baseline_prompt_loader_rejects_malformed_spec(tmp_config: NengokConfig) -> None:
    with pytest.raises(BaselinePromptError) as excinfo:
        load_baseline_prompt_loader("no-colon-here", config=tmp_config, phoenix=None)
    assert "malformed" in str(excinfo.value)


def test_load_baseline_prompt_loader_reports_missing_module(tmp_config: NengokConfig) -> None:
    with pytest.raises(BaselinePromptError) as excinfo:
        load_baseline_prompt_loader(
            "module_that_will_never_exist_42:make_loader",
            config=tmp_config,
            phoenix=None,
        )
    assert "module_that_will_never_exist_42" in str(excinfo.value)


def test_load_baseline_prompt_loader_rejects_wrong_return_type(
    tmp_config: NengokConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module_path = tmp_path / "bad_loader_factory.py"
    module_path.write_text(
        textwrap.dedent(
            """
            def build(config, phoenix):
                return "not-a-loader"
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(BaselinePromptError) as excinfo:
        load_baseline_prompt_loader(
            "bad_loader_factory:build",
            config=tmp_config,
            phoenix=None,
        )
    assert "BaselinePromptLoader" in str(excinfo.value)


def test_prompt_proposer_uses_injected_loader(tmp_config: NengokConfig) -> None:
    from nengok.core.fixer.prompt_proposer import PromptProposer

    class _Injected:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def load(self, project_name: str) -> str | None:
            self.calls.append(project_name)
            return "FROM-INJECTED-LOADER"

    injected = _Injected()
    config = replace(tmp_config, project_identifier="any-project")
    proposer = PromptProposer(config=config, baseline_loader=injected)

    assert proposer.load_baseline_prompt() == "FROM-INJECTED-LOADER"
    assert injected.calls == ["any-project"]


def test_baseline_loader_factory_signature(tmp_config: NengokConfig) -> None:
    """The default factory accepts (config, phoenix=None) so optional clients pass."""
    loader = default_loader(tmp_config, None)
    assert isinstance(loader, BaselinePromptLoader)


def test_baseline_prompt_loader_protocol_runtime_check() -> None:
    class _Conformant:
        def load(self, project_name: str) -> str | None:
            return None

    class _NotConformant:
        pass

    assert isinstance(_Conformant(), BaselinePromptLoader)
    assert not isinstance(_NotConformant(), BaselinePromptLoader)
