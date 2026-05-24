"""Round-trip a tiny dataset through Phoenix."""

from __future__ import annotations

import uuid

import pytest

from nengok.config import NengokConfig
from nengok.core.types import RegressionTestCase
from nengok.phoenix.client import PhoenixWrapper


@pytest.mark.slow
def test_create_dataset_round_trip(phoenix_config: NengokConfig) -> None:
    wrapper = PhoenixWrapper(phoenix_config)
    name = f"nengok-harness-{uuid.uuid4().hex[:8]}"
    cases = [
        RegressionTestCase(
            case_id=str(uuid.uuid4()),
            input={"prompt": "harness ping"},
            expected={"contains": "ping"},
            metadata={"source": "phoenix_harness"},
        )
    ]
    dataset = wrapper.create_dataset(name=name, cases=cases)
    assert dataset is not None
