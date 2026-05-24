"""FastAPI dependencies that hand routes the config and the state store."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Request

from nengok.config import NengokConfig
from nengok.state.store import StateStore


def get_config(request: Request) -> NengokConfig:
    return cast(NengokConfig, request.app.state.config)


ConfigDep = Annotated[NengokConfig, Depends(get_config)]


def get_store(config: ConfigDep) -> StateStore:
    return StateStore(config.state_db_path)


StoreDep = Annotated[StateStore, Depends(get_store)]
