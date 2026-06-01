"""
Behavior tests for the SQLAlchemy `ConnectionFactory` and the
`database_url` precedence in `NengokConfig.load()`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nengok import config as config_module
from nengok.config import NengokConfig
from nengok.errors import ConfigError
from nengok.state.connection import ConnectionFactory


def _load_with(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **env: str) -> NengokConfig:
    monkeypatch.setenv("PHOENIX_BASE_URL", "http://localhost:6006")
    monkeypatch.setenv("GOOGLE_API_KEY", "AIzaTEST")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return NengokConfig.load(config_path=tmp_path / "missing.toml")


def test_database_url_env_var_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg = _load_with(
        monkeypatch,
        tmp_path,
        DATABASE_URL="postgresql+psycopg://user:pw@db.local/nengok",
    )
    assert cfg.database_url == "postgresql+psycopg://user:pw@db.local/nengok"


def test_database_url_toml_used_when_env_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        "[nengok]\n"
        'phoenix_base_url = "http://localhost:6006"\n'
        'google_api_key = "AIzaTEST"\n'
        'database_url = "mysql+pymysql://user:pw@db.local/nengok"\n',
        encoding="utf-8",
    )
    cfg = NengokConfig.load(config_path=config_file)
    assert cfg.database_url == "mysql+pymysql://user:pw@db.local/nengok"


def test_database_url_defaults_to_sqlite(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    home = tmp_path / "fake-home"
    monkeypatch.setattr(config_module, "DEFAULT_STATE_DB", home / ".nengok" / "state.db")
    cfg = _load_with(monkeypatch, tmp_path)
    assert cfg.database_url is not None
    assert cfg.database_url.startswith("sqlite:///")
    assert cfg.database_url.endswith("/state.db")
    assert (home / ".nengok").is_dir()


def test_unsupported_dialect_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="is not supported"):
        _load_with(
            monkeypatch,
            tmp_path,
            DATABASE_URL="mongodb://localhost:27017/nengok",
        )


def test_malformed_database_url_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="could not be parsed"):
        _load_with(monkeypatch, tmp_path, DATABASE_URL="not-a-url")


def test_factory_builds_sqlite_engine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    cfg = _load_with(
        monkeypatch,
        tmp_path,
        DATABASE_URL=f"sqlite:///{db_path.as_posix()}",
    )
    factory = ConnectionFactory(cfg)
    engine = factory.engine()
    assert engine.dialect.name == "sqlite"

    with factory.connection() as conn:
        result = conn.exec_driver_sql("SELECT 1").scalar()
        assert result == 1

    factory.dispose()


def test_engine_repr_hides_password(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg = _load_with(
        monkeypatch,
        tmp_path,
        DATABASE_URL="postgresql+psycopg://nengok:s3cret-canary@db.local:5432/nengok",
    )
    factory = ConnectionFactory(cfg)
    engine = factory.engine()

    rendered = engine.url.render_as_string(hide_password=True)
    assert "s3cret-canary" not in rendered
    assert "***" in rendered

    assert "s3cret-canary" not in repr(engine)
    factory.dispose()


def test_factory_requires_resolved_url() -> None:
    cfg = NengokConfig(phoenix_base_url="http://localhost:6006", google_api_key="AIzaTEST")
    factory = ConnectionFactory(cfg)
    with pytest.raises(RuntimeError, match="database_url"):
        factory.engine()
