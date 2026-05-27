"""Live Phoenix prompt management: get_prompt_version and create-then-retrieve."""

from __future__ import annotations

import uuid

import pytest

from nengok.config import NengokConfig
from nengok.phoenix.client import PhoenixWrapper


@pytest.mark.slow
def test_get_prompt_version_returns_string_or_none(phoenix_config: NengokConfig) -> None:
    wrapper = PhoenixWrapper(phoenix_config)
    result = wrapper.get_prompt_version(name=phoenix_config.project_identifier)
    assert result is None or isinstance(result, str)


@pytest.mark.slow
def test_create_and_retrieve_prompt_version(phoenix_config: NengokConfig) -> None:
    wrapper = PhoenixWrapper(phoenix_config)
    prompt_name = f"nengok-harness-prompt-{uuid.uuid4().hex[:8]}"
    new_prompt = f"# Harness test prompt\nCreated by nengok phoenix_harness ({prompt_name})."

    wrapper._client.prompts.create(name=prompt_name, template=new_prompt)

    retrieved = wrapper.get_prompt_version(name=prompt_name)
    assert retrieved == new_prompt
