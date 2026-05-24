"""
Central configuration for the Nengok SDK.

Values are loaded with the following precedence:

    1. Constructor arguments to `NengokConfig(...)`
    2. Environment variables (`PHOENIX_BASE_URL`, `GOOGLE_API_KEY`, ...)
    3. `~/.nengok/config.toml` (written by `nengok init`)
    4. Hard-coded defaults below

The CLI calls `NengokConfig.load()` once at startup and threads the
resulting object through the orchestrator.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path.home() / ".nengok" / "config.toml"
DEFAULT_ARTIFACTS_DIR = Path("artifacts")
DEFAULT_STATE_DB = Path.home() / ".nengok" / "state.db"

DIAGNOSER_MODEL = "gemini-3.1-pro-preview"
JUDGE_MODEL = "gemini-3-flash-preview"

DEFAULT_SPAN_LIMIT = 200
DEFAULT_MIN_CLUSTER_SIZE = 3
DEFAULT_REGRESSION_PASS_THRESHOLD = 0.90
DEFAULT_GOLDEN_REGRESSION_LIMIT = 0.02
DEFAULT_DRY_RUN_SAMPLES = 3

DEFAULT_DASHBOARD_HOST = "127.0.0.1"
DEFAULT_DASHBOARD_PORT = 8765


@dataclass(frozen=True)
class NengokConfig:
    """Resolved Nengok configuration for a single CLI invocation."""

    phoenix_base_url: str
    phoenix_api_key: str | None = None
    google_api_key: str | None = None

    project_identifier: str = "default"

    diagnoser_model: str = DIAGNOSER_MODEL
    judge_model: str = JUDGE_MODEL

    span_limit: int = DEFAULT_SPAN_LIMIT
    min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE
    regression_pass_threshold: float = DEFAULT_REGRESSION_PASS_THRESHOLD
    golden_regression_limit: float = DEFAULT_GOLDEN_REGRESSION_LIMIT
    dry_run_samples: int = DEFAULT_DRY_RUN_SAMPLES

    artifacts_dir: Path = field(default_factory=lambda: DEFAULT_ARTIFACTS_DIR)
    state_db_path: Path = field(default_factory=lambda: DEFAULT_STATE_DB)

    dashboard_host: str = DEFAULT_DASHBOARD_HOST
    dashboard_port: int = DEFAULT_DASHBOARD_PORT

    @classmethod
    def load(cls, config_path: Path | None = None, **overrides: Any) -> NengokConfig:
        """
        Build a config from disk + env + explicit overrides.

        Constructor overrides win. `nengok init` writes the on-disk file;
        environment variables (e.g. `PHOENIX_API_KEY`) override the file
        so secrets never have to live on disk.
        """
        file_values = _read_config_file(config_path or DEFAULT_CONFIG_PATH)
        env_values = _read_env()

        merged: dict[str, Any] = {**file_values, **env_values, **overrides}

        if "phoenix_base_url" not in merged:
            raise ValueError(
                "Phoenix base URL not configured. "
                "Run `nengok init --phoenix-url <url>` or set PHOENIX_BASE_URL."
            )

        for path_key in ("artifacts_dir", "state_db_path"):
            if path_key in merged and not isinstance(merged[path_key], Path):
                merged[path_key] = Path(str(merged[path_key]))

        return cls(**merged)


def _read_config_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    return data.get("nengok", {})


def _read_env() -> dict[str, Any]:
    mapping = {
        "PHOENIX_BASE_URL": "phoenix_base_url",
        "PHOENIX_API_KEY": "phoenix_api_key",
        "GOOGLE_API_KEY": "google_api_key",
        "NENGOK_PROJECT": "project_identifier",
        "NENGOK_ARTIFACTS_DIR": "artifacts_dir",
        "NENGOK_STATE_DB": "state_db_path",
        "NENGOK_DASHBOARD_PORT": "dashboard_port",
    }
    out: dict[str, Any] = {}
    for env_key, config_key in mapping.items():
        value = os.environ.get(env_key)
        if value is None:
            continue
        if config_key == "dashboard_port":
            out[config_key] = int(value)
        else:
            out[config_key] = value
    return out
