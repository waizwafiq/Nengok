"""Tests for the dotted-path runner loader."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from nengok.errors import AgentRunnerLoadError
from nengok.runners import AgentRunner, SampleAgentRunner
from nengok.runners.loader import load_runner


def test_loader_returns_bundled_sample_runner() -> None:
    runner = load_runner("nengok.runners.sample_agent_runner:SampleAgentRunner")

    assert isinstance(runner, SampleAgentRunner)
    assert isinstance(runner, AgentRunner)
    assert runner.name == "travel-planner"


def test_loader_passes_kwargs_to_constructor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module_path = tmp_path / "ext_runner.py"
    module_path.write_text(
        textwrap.dedent(
            """
            from typing import Any


            class ConfigurableRunner:
                def __init__(self, *, agent_name: str, base_url: str) -> None:
                    self._name = agent_name
                    self.base_url = base_url

                @property
                def name(self) -> str:
                    return self._name

                def run(self, agent_input: dict, prompt: str) -> dict:
                    return {"name": self._name, "base_url": self.base_url}
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    runner = load_runner(
        "ext_runner:ConfigurableRunner",
        {"agent_name": "custom", "base_url": "https://api.example.com"},
    )

    assert runner.name == "custom"
    assert runner.run({}, "p") == {"name": "custom", "base_url": "https://api.example.com"}


def test_loader_rejects_class_missing_run_method(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module_path = tmp_path / "broken_runner.py"
    module_path.write_text(
        textwrap.dedent(
            """
            class HalfBakedRunner:
                @property
                def name(self) -> str:
                    return "broken"
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(AgentRunnerLoadError) as excinfo:
        load_runner("broken_runner:HalfBakedRunner")

    message = str(excinfo.value)
    assert "HalfBakedRunner" in message
    assert "run(agent_input: dict, prompt: str) -> dict" in message


def test_loader_rejects_class_missing_name_property(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module_path = tmp_path / "nameless_runner.py"
    module_path.write_text(
        textwrap.dedent(
            """
            class NamelessRunner:
                def run(self, agent_input: dict, prompt: str) -> dict:
                    return {}
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(AgentRunnerLoadError) as excinfo:
        load_runner("nameless_runner:NamelessRunner")

    assert "name" in str(excinfo.value)


def test_loader_rejects_malformed_spec() -> None:
    with pytest.raises(AgentRunnerLoadError) as excinfo:
        load_runner("nengok.runners.sample_agent_runner")
    assert "malformed" in str(excinfo.value)

    with pytest.raises(AgentRunnerLoadError):
        load_runner("nengok.runners.sample_agent_runner:Foo:Bar")


def test_loader_reports_missing_module() -> None:
    with pytest.raises(AgentRunnerLoadError) as excinfo:
        load_runner("does_not_exist_module_8675309:SomeClass")
    message = str(excinfo.value)
    assert "does_not_exist_module_8675309" in message
    assert "PYTHONPATH" in message


def test_loader_reports_missing_class(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module_path = tmp_path / "empty_module.py"
    module_path.write_text("# nothing here\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(AgentRunnerLoadError) as excinfo:
        load_runner("empty_module:MissingClass")

    assert "MissingClass" in str(excinfo.value)


def test_loader_reports_constructor_kwarg_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module_path = tmp_path / "strict_runner.py"
    module_path.write_text(
        textwrap.dedent(
            """
            class StrictRunner:
                def __init__(self) -> None:
                    pass

                @property
                def name(self) -> str:
                    return "strict"

                def run(self, agent_input: dict, prompt: str) -> dict:
                    return {}
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(AgentRunnerLoadError) as excinfo:
        load_runner("strict_runner:StrictRunner", {"unexpected_kwarg": 1})

    assert "agent_runner_kwargs" in str(excinfo.value)


def _drop_module(name: str) -> None:
    sys.modules.pop(name, None)


def test_loader_does_not_cache_failed_imports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _drop_module("late_module")
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(AgentRunnerLoadError):
        load_runner("late_module:LateRunner")

    (tmp_path / "late_module.py").write_text(
        textwrap.dedent(
            """
            class LateRunner:
                @property
                def name(self) -> str:
                    return "late"

                def run(self, agent_input: dict, prompt: str) -> dict:
                    return {"ok": True}
            """
        ),
        encoding="utf-8",
    )

    runner = load_runner("late_module:LateRunner")
    assert runner.run({}, "p") == {"ok": True}
