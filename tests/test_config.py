"""Config loader behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from nengok.config import NengokConfig
from nengok.errors import ConfigError


def test_load_requires_phoenix_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PHOENIX_BASE_URL", raising=False)
    with pytest.raises(ConfigError, match="Phoenix base URL not configured"):
        NengokConfig.load(config_path=tmp_path / "missing.toml")


def test_overrides_take_precedence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PHOENIX_BASE_URL", "http://from-env")
    monkeypatch.setenv("GOOGLE_API_KEY", "AIzaTEST")
    config = NengokConfig.load(
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://from-override",
    )
    assert config.phoenix_base_url == "http://from-override"


def test_env_provides_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PHOENIX_BASE_URL", "http://from-env")
    monkeypatch.setenv("GOOGLE_API_KEY", "AIzaTEST")
    config = NengokConfig.load(config_path=tmp_path / "missing.toml")
    assert config.phoenix_base_url == "http://from-env"


def test_env_parses_vertex_backend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PHOENIX_BASE_URL", "http://localhost:6006")
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "vtx-proj")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    config = NengokConfig.load(config_path=tmp_path / "missing.toml")
    assert config.gemini_use_vertex is True
    assert config.vertex_project == "vtx-proj"
    assert config.vertex_location == "us-central1"


def test_env_vertex_flag_false_value(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PHOENIX_BASE_URL", "http://localhost:6006")
    monkeypatch.setenv("GOOGLE_API_KEY", "AIzaTEST")
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "0")
    config = NengokConfig.load(config_path=tmp_path / "missing.toml")
    assert config.gemini_use_vertex is False


def test_env_parses_metrics_enabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PHOENIX_BASE_URL", "http://localhost:6006")
    monkeypatch.setenv("GOOGLE_API_KEY", "AIzaTEST")
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "false")
    monkeypatch.setenv("NENGOK_METRICS_ENABLED", "true")
    config = NengokConfig.load(config_path=tmp_path / "missing.toml")
    assert config.metrics_enabled is True
