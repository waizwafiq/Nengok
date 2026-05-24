"""Shared fixtures for the live Phoenix harness."""

from __future__ import annotations

import os

import pytest

from nengok.config import NengokConfig


@pytest.fixture(scope="session")
def phoenix_config() -> NengokConfig:
    base_url = os.environ.get("PHOENIX_BASE_URL")
    if not base_url:
        pytest.skip("PHOENIX_BASE_URL is not set; skipping live Phoenix harness.")
    return NengokConfig.load()
