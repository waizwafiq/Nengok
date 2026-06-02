"""
Cover the TLS posture decisions in `ConnectionFactory._build_engine`.

The tests exercise `_apply_tls_posture` directly because it owns every
decision and pure-function checks do not require an actual database. A
non-loopback Postgres URL without an `sslmode` parameter gains
`sslmode=require`; a loopback URL is left alone; the
`database_allow_plaintext` opt-out skips the rewrite and logs a
WARNING.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from nengok.config import NengokConfig
from nengok.state.connection import ConnectionFactory, _apply_tls_posture


@pytest.fixture
def base_config(tmp_path: Path) -> NengokConfig:
    return NengokConfig(
        phoenix_base_url="http://localhost:6006",
        google_api_key="ai-studio-test-key",
        project_identifier="test-project",
        state_db_path=tmp_path / "state.db",
        database_url=f"sqlite:///{(tmp_path / 'state.db').as_posix()}",
    )


def test_remote_postgres_gains_sslmode_require() -> None:
    url = make_url("postgresql+psycopg://nengok:secret@db.internal:5432/app")
    rewritten = _apply_tls_posture(url, allow_plaintext=False)
    assert rewritten.query.get("sslmode") == "require"


def test_remote_postgres_keeps_existing_sslmode() -> None:
    url = make_url("postgresql+psycopg://nengok:secret@db.internal:5432/app?sslmode=verify-full")
    rewritten = _apply_tls_posture(url, allow_plaintext=False)
    assert rewritten.query.get("sslmode") == "verify-full"


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
def test_loopback_postgres_keeps_url_unchanged(host: str) -> None:
    url = make_url(f"postgresql+psycopg://nengok:secret@{host}:5432/app")
    rewritten = _apply_tls_posture(url, allow_plaintext=False)
    assert "sslmode" not in rewritten.query


def test_allow_plaintext_skips_rewrite_and_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    url = make_url("postgresql+psycopg://nengok:secret@db.internal:5432/app")
    with caplog.at_level(logging.WARNING, logger="nengok.state.connection"):
        rewritten = _apply_tls_posture(url, allow_plaintext=True)
    assert "sslmode" not in rewritten.query
    assert any(
        "plaintext" in record.getMessage() and "db.internal" in record.getMessage()
        for record in caplog.records
    )


def test_remote_mysql_gains_ssl_parameter() -> None:
    url = make_url("mysql+pymysql://nengok:secret@db.internal:3306/app")
    rewritten = _apply_tls_posture(url, allow_plaintext=False)
    assert rewritten.query.get("ssl") == "true"


def test_remote_mysql_keeps_existing_ssl_parameter() -> None:
    url = make_url("mysql+pymysql://nengok:secret@db.internal:3306/app?ssl_ca=/etc/ca.pem")
    rewritten = _apply_tls_posture(url, allow_plaintext=False)
    assert "ssl" not in rewritten.query
    assert rewritten.query.get("ssl_ca") == "/etc/ca.pem"


def test_sqlite_url_is_untouched(base_config: NengokConfig) -> None:
    factory = ConnectionFactory(base_config)
    try:
        engine = factory.engine()
        assert engine.url.drivername == "sqlite"
    finally:
        factory.dispose()


def test_factory_appends_sslmode_for_remote_postgres(base_config: NengokConfig) -> None:
    config = replace(
        base_config,
        database_url="postgresql+psycopg://nengok:secret@db.internal:5432/app",
    )
    factory = ConnectionFactory(config)
    try:
        engine = factory.engine()
        assert engine.url.query.get("sslmode") == "require"
    finally:
        factory.dispose()


def test_factory_honors_allow_plaintext(base_config: NengokConfig, caplog: pytest.LogCaptureFixture) -> None:
    config = replace(
        base_config,
        database_url="postgresql+psycopg://nengok:secret@db.internal:5432/app",
        database_allow_plaintext=True,
    )
    factory = ConnectionFactory(config)
    try:
        with caplog.at_level(logging.WARNING, logger="nengok.state.connection"):
            engine = factory.engine()
        assert "sslmode" not in engine.url.query
        assert any("plaintext" in record.getMessage() for record in caplog.records)
    finally:
        factory.dispose()
