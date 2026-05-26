"""Error-message contract tests for the typed exceptions in `nengok.errors`."""

from __future__ import annotations

from dataclasses import replace

import pytest

from nengok.config import NengokConfig
from nengok.core.diagnoser.clusterer import Clusterer
from nengok.core.diagnoser.hypothesizer import Hypothesizer
from nengok.core.fixer.prompt_proposer import PromptProposer
from nengok.core.fixer.test_generator import TestGenerator
from nengok.errors import (
    BaselinePromptError,
    MissingApiKeyError,
    NengokError,
    OptionalDependencyError,
)


def _no_key_config(tmp_config: NengokConfig) -> NengokConfig:
    return replace(tmp_config, google_api_key=None)


def test_clusterer_missing_key_names_role_and_env_var(
    tmp_config: NengokConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    clusterer = Clusterer(config=_no_key_config(tmp_config))

    with pytest.raises(MissingApiKeyError) as excinfo:
        clusterer._default_gemini_call("ignored")

    assert excinfo.value.role == "Clusterer"
    assert "GOOGLE_API_KEY" in str(excinfo.value)
    assert "aistudio.google.com" in str(excinfo.value)


def test_hypothesizer_missing_key_role_attribution(
    tmp_config: NengokConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    hypothesizer = Hypothesizer(config=_no_key_config(tmp_config))

    with pytest.raises(MissingApiKeyError) as excinfo:
        hypothesizer._default_gemini_call("ignored")

    assert excinfo.value.role == "Hypothesizer"


def test_test_generator_missing_key_role_attribution(
    tmp_config: NengokConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    generator = TestGenerator(config=_no_key_config(tmp_config))

    with pytest.raises(MissingApiKeyError) as excinfo:
        generator._default_gemini_call("ignored")

    assert excinfo.value.role == "Test Generator"


def test_prompt_proposer_missing_key_role_attribution(
    tmp_config: NengokConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    proposer = PromptProposer(config=_no_key_config(tmp_config))

    with pytest.raises(MissingApiKeyError) as excinfo:
        proposer._default_gemini_call("ignored")

    assert excinfo.value.role == "Prompt Proposer"


def test_baseline_prompt_error_includes_project_identifier(tmp_config: NengokConfig) -> None:
    config = replace(tmp_config, project_identifier="missing-agent")
    proposer = PromptProposer(config=config)

    with pytest.raises(BaselinePromptError) as excinfo:
        proposer.load_baseline_prompt()

    assert excinfo.value.project_identifier == "missing-agent"


def test_optional_dependency_error_carries_install_hint() -> None:
    exc = OptionalDependencyError("phoenix missing", install_hint="pip install nengok[phoenix]")

    assert exc.install_hint == "pip install nengok[phoenix]"
    assert isinstance(exc, NengokError)


def test_typed_errors_all_inherit_from_nengok_error() -> None:
    samples: list[NengokError] = [
        MissingApiKeyError("x", role="Role"),
        OptionalDependencyError("x", install_hint="pip install y"),
        BaselinePromptError("x", project_identifier="p"),
    ]

    for exc in samples:
        assert isinstance(exc, NengokError)
