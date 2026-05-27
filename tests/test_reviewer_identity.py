"""Coverage for the reviewer identity module and its CLI surface."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from nengok.cli import app
from nengok.reviewer import (
    ANONYMOUS_REVIEWER,
    REVIEWER_ENV_VAR,
    format_identity,
    resolve_reviewer,
    write_identity,
)


def test_format_identity_with_email_uses_git_style() -> None:
    assert format_identity("Alice Smith", "alice@example.com") == "Alice Smith <alice@example.com>"


def test_format_identity_without_email_returns_name_only() -> None:
    assert format_identity("Alice Smith", None) == "Alice Smith"


def test_format_identity_blank_email_drops_brackets() -> None:
    assert format_identity("Alice", "   ") == "Alice"


def test_format_identity_trims_surrounding_whitespace() -> None:
    assert format_identity("  Alice  ", "  alice@example.com  ") == "Alice <alice@example.com>"


def test_format_identity_rejects_empty_name() -> None:
    with pytest.raises(ValueError):
        format_identity("   ", "alice@example.com")


def test_write_identity_creates_parent_and_trailing_newline(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "reviewer.txt"
    result = write_identity("Alice <alice@example.com>", path=target)

    assert result == target
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "Alice <alice@example.com>\n"


def test_write_identity_overwrites_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "reviewer.txt"
    target.write_text("old\n", encoding="utf-8")

    write_identity("Bob", path=target)

    assert target.read_text(encoding="utf-8") == "Bob\n"


def test_resolve_reviewer_picks_request_body_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_path = tmp_path / "reviewer.txt"
    file_path.write_text("from-file\n", encoding="utf-8")
    monkeypatch.setattr("nengok.reviewer.REVIEWER_FILE_PATH", file_path)
    monkeypatch.setenv(REVIEWER_ENV_VAR, "from-env")

    identity, source = resolve_reviewer("Alice")

    assert (identity, source) == ("Alice", "request")


def test_resolve_reviewer_picks_file_before_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_path = tmp_path / "reviewer.txt"
    file_path.write_text("from-file\n", encoding="utf-8")
    monkeypatch.setattr("nengok.reviewer.REVIEWER_FILE_PATH", file_path)
    monkeypatch.setenv(REVIEWER_ENV_VAR, "from-env")

    identity, source = resolve_reviewer(None)

    assert (identity, source) == ("from-file", "file")


def test_resolve_reviewer_falls_back_to_env_when_file_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("nengok.reviewer.REVIEWER_FILE_PATH", tmp_path / "missing.txt")
    monkeypatch.setenv(REVIEWER_ENV_VAR, "from-env")

    assert resolve_reviewer(None) == ("from-env", "env")


def test_resolve_reviewer_falls_back_to_anonymous_when_nothing_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("nengok.reviewer.REVIEWER_FILE_PATH", tmp_path / "missing.txt")
    monkeypatch.delenv(REVIEWER_ENV_VAR, raising=False)

    assert resolve_reviewer(None) == (ANONYMOUS_REVIEWER, "fallback")


def test_resolve_reviewer_ignores_empty_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_path = tmp_path / "reviewer.txt"
    file_path.write_text("  \n", encoding="utf-8")
    monkeypatch.setattr("nengok.reviewer.REVIEWER_FILE_PATH", file_path)
    monkeypatch.setenv(REVIEWER_ENV_VAR, "from-env")

    assert resolve_reviewer(None) == ("from-env", "env")


def test_reviewer_set_cli_writes_name_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_path = tmp_path / "reviewer.txt"
    monkeypatch.setattr("nengok.reviewer.REVIEWER_FILE_PATH", file_path)

    runner = CliRunner()
    result = runner.invoke(app, ["reviewer", "set", "Alice"])

    assert result.exit_code == 0, result.output
    assert file_path.read_text(encoding="utf-8") == "Alice\n"
    assert "Alice" in result.output


def test_reviewer_set_cli_with_email_writes_git_style(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file_path = tmp_path / "reviewer.txt"
    monkeypatch.setattr("nengok.reviewer.REVIEWER_FILE_PATH", file_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["reviewer", "set", "Alice Smith", "--email", "alice@example.com"],
    )

    assert result.exit_code == 0, result.output
    assert file_path.read_text(encoding="utf-8") == "Alice Smith <alice@example.com>\n"


def test_reviewer_set_cli_rejects_empty_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_path = tmp_path / "reviewer.txt"
    monkeypatch.setattr("nengok.reviewer.REVIEWER_FILE_PATH", file_path)

    runner = CliRunner()
    result = runner.invoke(app, ["reviewer", "set", "   "])

    assert result.exit_code == 2
    assert not file_path.exists()


def test_reviewer_show_reports_file_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_path = tmp_path / "reviewer.txt"
    file_path.write_text("Alice <alice@example.com>\n", encoding="utf-8")
    monkeypatch.setattr("nengok.reviewer.REVIEWER_FILE_PATH", file_path)
    monkeypatch.delenv(REVIEWER_ENV_VAR, raising=False)

    runner = CliRunner()
    result = runner.invoke(app, ["reviewer", "show"])

    assert result.exit_code == 0, result.output
    assert "reviewer: Alice <alice@example.com>" in result.output
    assert "source:   file" in result.output


def test_reviewer_show_reports_fallback_with_hint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nengok.reviewer.REVIEWER_FILE_PATH", tmp_path / "missing.txt")
    monkeypatch.delenv(REVIEWER_ENV_VAR, raising=False)

    runner = CliRunner()
    result = runner.invoke(app, ["reviewer", "show"])

    assert result.exit_code == 0, result.output
    assert f"reviewer: {ANONYMOUS_REVIEWER}" in result.output
    assert "source:   fallback" in result.output
    assert "nengok reviewer set" in result.output


def test_reviewer_set_round_trips_through_resolve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_path = tmp_path / "reviewer.txt"
    monkeypatch.setattr("nengok.reviewer.REVIEWER_FILE_PATH", file_path)
    monkeypatch.delenv(REVIEWER_ENV_VAR, raising=False)

    runner = CliRunner()
    set_result = runner.invoke(
        app,
        ["reviewer", "set", "Alice", "--email", "alice@example.com"],
    )
    assert set_result.exit_code == 0, set_result.output

    identity, source = resolve_reviewer(None)
    assert identity == "Alice <alice@example.com>"
    assert source == "file"
