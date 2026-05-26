"""
Config templates shipped with the SDK.

The three `.toml` files in this directory are the canonical, package-
resident copies of `examples/*.toml` at the repo root. The wizard and
`nengok config init` render one of these and apply user-provided
overrides on top, so the on-disk config always starts from a fully
documented baseline rather than being constructed line-by-line.

The repo-root `examples/` copies exist for browsing on GitHub. A test
in `tests/test_config_templates.py` asserts they stay byte-identical
to the package copies.
"""

from __future__ import annotations

from collections.abc import Iterable
from importlib.resources import files
from pathlib import Path

TEMPLATE_NAMES: tuple[str, ...] = ("local", "cloud", "qa-agent")


def list_templates() -> Iterable[str]:
    return TEMPLATE_NAMES


def template_filename(name: str) -> str:
    if name not in TEMPLATE_NAMES:
        raise ValueError(f"Unknown template '{name}'. Available templates: {', '.join(TEMPLATE_NAMES)}.")
    return f"config-{name}.toml"


def read_template(name: str) -> str:
    """
    Return the raw TOML text for the named template.

    Works in both editable installs and wheel installs because the
    templates live as package data under `nengok/templates/`.
    """
    resource = files(__name__) / template_filename(name)
    return resource.read_text(encoding="utf-8")


def template_path(name: str) -> Path:
    """Filesystem path to the template, for tests and `--diff`-style tooling."""
    resource = files(__name__) / template_filename(name)
    return Path(str(resource))
