"""
Reviewer identity helpers shared by the CLI and the dashboard.

A reviewer string identifies the human who approved or rejected a
cluster. The dashboard resolves it once per approval; the CLI writes
the persistent default via `nengok reviewer set`.
"""

from __future__ import annotations

import os
from pathlib import Path

REVIEWER_ENV_VAR = "NENGOK_REVIEWER"
REVIEWER_FILE_PATH = Path.home() / ".nengok" / "reviewer.txt"
ANONYMOUS_REVIEWER = "anonymous"


def resolve_reviewer(provided: str | None) -> tuple[str, str]:
    """
    Return the reviewer string to record plus its provenance.

    Order: explicit body field, then `~/.nengok/reviewer.txt`
    (managed by `nengok reviewer set`), then `NENGOK_REVIEWER`,
    then the literal "anonymous". File wins over env so a per-user
    CLI identity is not silently overridden by a deployment-wide
    env var.
    """
    if provided:
        trimmed = provided.strip()
        if trimmed:
            return trimmed, "request"
    if REVIEWER_FILE_PATH.is_file():
        file_value = REVIEWER_FILE_PATH.read_text(encoding="utf-8").strip()
        if file_value:
            return file_value, "file"
    env_value = os.environ.get(REVIEWER_ENV_VAR, "").strip()
    if env_value:
        return env_value, "env"
    return ANONYMOUS_REVIEWER, "fallback"


def format_identity(name: str, email: str | None) -> str:
    """
    Render a `Name <email>` string when email is supplied, else `Name`.

    Matches git's `user.name`/`user.email` rendering so the audit log
    stays human-readable and emails are easy to grep.
    """
    cleaned_name = name.strip()
    if not cleaned_name:
        raise ValueError("reviewer name must not be empty")
    if email is None:
        return cleaned_name
    cleaned_email = email.strip()
    if not cleaned_email:
        return cleaned_name
    return f"{cleaned_name} <{cleaned_email}>"


def write_identity(identity: str, *, path: Path = REVIEWER_FILE_PATH) -> Path:
    """
    Persist `identity` to `path`, creating the parent directory.

    Writes a single trailing newline so the file follows POSIX
    conventions and round-trips cleanly through `read_text().strip()`.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"{identity}\n", encoding="utf-8")
    return target
