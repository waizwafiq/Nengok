"""
Cover the privilege-probe branches: SQLite info, Postgres flag detection,
MySQL grant parsing, and engine failure modes.

The Postgres and MySQL branches drive SQLAlchemy through a stub engine
because the CI runners do not ship a server. The stubs return the
result shape `pg_roles` / `SHOW GRANTS` produce so the probe walks the
same code paths it would against a real database.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from nengok.config import NengokConfig
from nengok.diagnostics import db_privileges
from nengok.diagnostics.base import ProbeStatus
from nengok.diagnostics.db_privileges import probe_db_privileges


@pytest.fixture
def base_config(tmp_path: Path) -> NengokConfig:
    return NengokConfig(
        phoenix_base_url="http://localhost:6006",
        google_api_key="ai-studio-test-key",
        project_identifier="test-project",
        state_db_path=tmp_path / "state.db",
        database_url=f"sqlite:///{(tmp_path / 'state.db').as_posix()}",
    )


def test_sqlite_emits_info(base_config: NengokConfig) -> None:
    result = probe_db_privileges(base_config)
    assert result.status is ProbeStatus.OK
    assert "sqlite" in result.detail.lower()


def test_missing_database_url_warns(base_config: NengokConfig) -> None:
    config = replace(base_config, database_url=None)
    result = probe_db_privileges(config)
    assert result.status is ProbeStatus.WARN
    assert "database_url" in result.detail


class _FakeRow:
    def __init__(self, **values: Any) -> None:
        for key, value in values.items():
            setattr(self, key, value)
        self._values = values

    def __iter__(self) -> Any:
        return iter(self._values.values())


class _FakeResult:
    def __init__(self, rows: Sequence[_FakeRow]) -> None:
        self._rows = list(rows)

    def first(self) -> _FakeRow | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[_FakeRow]:
        return list(self._rows)


class _FakeConnection:
    def __init__(self, responses: dict[str, _FakeResult]) -> None:
        self._responses = responses

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement: Any) -> _FakeResult:
        sql = str(statement)
        for key, result in self._responses.items():
            if key.lower() in sql.lower():
                return result
        raise AssertionError(f"unexpected SQL: {sql}")


class _FakeEngine:
    def __init__(self, responses: dict[str, _FakeResult]) -> None:
        self._responses = responses

    def connect(self) -> _FakeConnection:
        return _FakeConnection(self._responses)


def _install_fake_engine(monkeypatch: pytest.MonkeyPatch, responses: dict[str, _FakeResult]) -> None:
    class _FakeFactory:
        def __init__(self, _config: NengokConfig) -> None:
            self._engine = _FakeEngine(responses)

        def engine(self) -> _FakeEngine:
            return self._engine

        def dispose(self) -> None:
            return None

    monkeypatch.setattr(db_privileges, "ConnectionFactory", _FakeFactory)


def test_postgres_superuser_fails(base_config: NengokConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    config = replace(
        base_config,
        database_url="postgresql+psycopg://nengok:secret@db.internal/app",
    )
    _install_fake_engine(
        monkeypatch,
        {
            "pg_roles": _FakeResult(
                [_FakeRow(rolsuper=True, rolcreatedb=False, rolcreaterole=False, who="nengok")]
            )
        },
    )
    result = probe_db_privileges(config)
    assert result.status is ProbeStatus.FAIL
    assert "SUPERUSER" in result.detail
    assert "docs/database-grants.md" in (result.fix_hint or "")


def test_postgres_createdb_fails(base_config: NengokConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    config = replace(
        base_config,
        database_url="postgresql+psycopg://nengok:secret@db.internal/app",
    )
    _install_fake_engine(
        monkeypatch,
        {
            "pg_roles": _FakeResult(
                [_FakeRow(rolsuper=False, rolcreatedb=True, rolcreaterole=False, who="nengok")]
            )
        },
    )
    result = probe_db_privileges(config)
    assert result.status is ProbeStatus.FAIL
    assert "CREATEDB" in result.detail


def test_postgres_least_privilege_passes(base_config: NengokConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    config = replace(
        base_config,
        database_url="postgresql+psycopg://nengok:secret@db.internal/app",
    )
    _install_fake_engine(
        monkeypatch,
        {
            "pg_roles": _FakeResult(
                [_FakeRow(rolsuper=False, rolcreatedb=False, rolcreaterole=False, who="nengok")]
            )
        },
    )
    result = probe_db_privileges(config)
    assert result.status is ProbeStatus.OK
    assert "scoped" in result.detail.lower()


def test_mysql_all_privileges_fails(base_config: NengokConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    config = replace(
        base_config,
        database_url="mysql+pymysql://nengok:secret@db.internal/app",
    )
    _install_fake_engine(
        monkeypatch,
        {
            "SHOW GRANTS": _FakeResult(
                [
                    _FakeRow(grant="GRANT ALL PRIVILEGES ON *.* TO 'nengok'@'%'"),
                    _FakeRow(
                        grant="GRANT SELECT, INSERT, UPDATE, DELETE ON `app`.`nengok_%` TO 'nengok'@'%'"
                    ),
                ]
            ),
            "CURRENT_USER": _FakeResult([_FakeRow(who="nengok@%")]),
        },
    )
    result = probe_db_privileges(config)
    assert result.status is ProbeStatus.FAIL
    assert "ALL PRIVILEGES" in result.detail


def test_mysql_least_privilege_passes(base_config: NengokConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    config = replace(
        base_config,
        database_url="mysql+pymysql://nengok:secret@db.internal/app",
    )
    _install_fake_engine(
        monkeypatch,
        {
            "SHOW GRANTS": _FakeResult(
                [
                    _FakeRow(grant="GRANT USAGE ON *.* TO 'nengok'@'%'"),
                    _FakeRow(
                        grant="GRANT CREATE, ALTER, INDEX, INSERT, UPDATE, DELETE, SELECT "
                        "ON `app`.`nengok_%` TO 'nengok'@'%'"
                    ),
                ]
            ),
            "CURRENT_USER": _FakeResult([_FakeRow(who="nengok@%")]),
        },
    )
    result = probe_db_privileges(config)
    assert result.status is ProbeStatus.OK
    assert "no over-broad" in result.detail.lower()


def test_engine_build_failure_reports_safe_url(
    base_config: NengokConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = replace(
        base_config,
        database_url="postgresql+psycopg://nengok:sup3r-secret@db.internal/app",
    )

    class _BadFactory:
        def __init__(self, _config: NengokConfig) -> None:
            pass

        def engine(self) -> Any:
            raise RuntimeError("no engine for you")

        def dispose(self) -> None:
            return None

    monkeypatch.setattr(db_privileges, "ConnectionFactory", _BadFactory)
    result = probe_db_privileges(config)
    assert result.status is ProbeStatus.FAIL
    assert "sup3r-secret" not in result.detail
    assert "***" in result.detail
