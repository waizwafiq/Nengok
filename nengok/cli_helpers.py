"""
Helpers used by the CLI that are import-light enough to call from `nengok init`
without pulling in the full orchestrator stack.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from typing import Any

from nengok import templates

SECRET_FIELD_PATTERN = re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization)")


def write_config_file(
    *,
    config_path: Path,
    phoenix_base_url: str,
    phoenix_api_key: str | None,
    project_identifier: str,
    google_api_key: str | None = None,
    agent_runner: str | None = None,
    template_name: str | None = None,
) -> Path:
    """
    Render `~/.nengok/config.toml` from a documented template.

    The template ships every available knob as a commented default, so
    the on-disk file always starts from a documented baseline. Required
    values (Phoenix URL, project, optional API keys, optional agent
    runner) are overlaid on top with line-level substitutions. API keys
    are only written to disk if the caller passed them explicitly; the
    recommended pattern is to leave keys in the environment so the
    on-disk config can be safely committed to a private dotfile repo.
    """
    config_path.parent.mkdir(parents=True, exist_ok=True)
    chosen = template_name or _pick_template(
        phoenix_base_url=phoenix_base_url,
        project_identifier=project_identifier,
        agent_runner=agent_runner,
    )
    body = render_template(
        chosen,
        phoenix_base_url=phoenix_base_url,
        phoenix_api_key=phoenix_api_key,
        google_api_key=google_api_key,
        project_identifier=project_identifier,
        agent_runner=agent_runner,
    )
    config_path.write_text(body, encoding="utf-8")
    return config_path


def render_template(
    name: str,
    *,
    phoenix_base_url: str | None = None,
    phoenix_api_key: str | None = None,
    google_api_key: str | None = None,
    project_identifier: str | None = None,
    agent_runner: str | None = None,
) -> str:
    """
    Render a named template, optionally overlaying user-provided fields.

    Passing nothing returns the template verbatim, which is what
    `nengok config init --template <name>` writes. The wizard passes
    the values it collected so the resulting config is ready to run.
    """
    body = templates.read_template(name)
    if phoenix_base_url is not None:
        body = _set_string_value(body, "phoenix_base_url", phoenix_base_url)
    if project_identifier is not None:
        body = _set_string_value(body, "project_identifier", project_identifier)
    if phoenix_api_key:
        body = _set_or_uncomment_string(body, "phoenix_api_key", phoenix_api_key)
    if google_api_key:
        body = _set_or_uncomment_string(body, "google_api_key", google_api_key)
    if agent_runner:
        body = _set_or_uncomment_string(body, "agent_runner", agent_runner)
    return body


def _pick_template(*, phoenix_base_url: str, project_identifier: str, agent_runner: str | None) -> str:
    """Choose the closest template based on the values the wizard collected."""
    if agent_runner and "qa_agent" in agent_runner:
        return "qa-agent"
    if project_identifier == "qa-agent":
        return "qa-agent"
    if "phoenix.arize.com" in phoenix_base_url:
        return "cloud"
    return "local"


def _set_string_value(body: str, key: str, value: str) -> str:
    """Replace `key = "..."` with the new value, preserving line position."""
    pattern = re.compile(rf'^({re.escape(key)})\s*=\s*".*"\s*$', re.MULTILINE)
    replacement = f'{key} = "{_escape_toml_string(value)}"'
    return pattern.sub(replacement, body, count=1)


def _set_or_uncomment_string(body: str, key: str, value: str) -> str:
    """
    Set `key = "value"` whether the line is already active or still commented.

    Falls through to appending under `[nengok]` if neither form is in
    the template, so a forward-compatible loader does not silently drop
    a value the user supplied.
    """
    new_line = f'{key} = "{_escape_toml_string(value)}"'

    active = re.compile(rf'^({re.escape(key)})\s*=\s*".*"\s*$', re.MULTILINE)
    if active.search(body):
        return active.sub(new_line, body, count=1)

    commented = re.compile(rf"^#\s*{re.escape(key)}\s*=.*$", re.MULTILINE)
    if commented.search(body):
        return commented.sub(new_line, body, count=1)

    return _append_under_nengok_section(body, new_line)


def _append_under_nengok_section(body: str, line: str) -> str:
    header = "[nengok]"
    idx = body.find(header)
    if idx < 0:
        return body.rstrip() + "\n\n[nengok]\n" + line + "\n"
    section_end = body.find("\n\n", idx)
    if section_end < 0:
        return body.rstrip() + "\n" + line + "\n"
    return body[:section_end] + "\n" + line + body[section_end:]


def _escape_toml_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def mask_secret(value: str | None) -> str:
    """
    Mask a secret-shaped string as `<prefix>****<suffix>` for safe display.

    Returns `<unset>` for `None`. Values of nine characters or fewer are
    fully masked so a short token does not effectively print itself.
    """
    if value is None:
        return "<unset>"
    if not isinstance(value, str):
        value = str(value)
    if len(value) <= 9:
        return "****"
    return f"{value[:4]}****{value[-4:]}"


def format_config_for_display(config: Any) -> str:
    """
    Render the loaded config as `key = value` lines with secrets masked.

    Walks the dataclass fields in declaration order so the output stays
    stable across runs. Fields whose name matches `SECRET_FIELD_PATTERN`
    (e.g. `google_api_key`, `dashboard_auth_token`) are routed through
    `mask_secret`; everything else is printed verbatim. The caller is
    free to pipe the result into a paste buffer without leaking keys.
    """
    if not dataclasses.is_dataclass(config):
        raise TypeError("format_config_for_display expects a dataclass instance")

    lines: list[str] = []
    for f in dataclasses.fields(config):
        value = getattr(config, f.name)
        if SECRET_FIELD_PATTERN.search(f.name):
            rendered = mask_secret(value if isinstance(value, str) else None)
        elif value is None:
            rendered = "<unset>"
        else:
            rendered = repr(value) if isinstance(value, str) else str(value)
        lines.append(f"{f.name} = {rendered}")
    return "\n".join(lines)
