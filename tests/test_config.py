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
