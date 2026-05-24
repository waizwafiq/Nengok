"""Shared fixtures for the unit-test suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from nengok.config import NengokConfig


@pytest.fixture
def tmp_config(tmp_path: Path) -> NengokConfig:
    return NengokConfig.load(
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://localhost:6006",
        phoenix_api_key=None,
        google_api_key=None,
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
    )
