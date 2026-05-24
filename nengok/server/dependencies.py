"""FastAPI dependencies that hand routes the config and the state store."""

from __future__ import annotations

from fastapi import Depends, Request

from nengok.config import NengokConfig
from nengok.state.store import StateStore


def get_config(request: Request) -> NengokConfig:
    return request.app.state.config


def get_store(config: NengokConfig = Depends(get_config)) -> StateStore:
    return StateStore(config.state_db_path)
