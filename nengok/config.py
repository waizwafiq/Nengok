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

import logging
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from nengok.errors import ConfigError

logger = logging.getLogger(__name__)

SAMPLE_AGENT_PROJECT_NAME = "travel-planner-agent"

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
DEFAULT_CLUSTER_TRACE_CHAR_BUDGET = 2000

DEFAULT_DASHBOARD_HOST = "127.0.0.1"
DEFAULT_DASHBOARD_PORT = 8765

DEFAULT_MCP_PACKAGE = "@arizeai/phoenix-mcp@4.0.13"
DEFAULT_MCP_NPX_COMMAND = "npx"
DEFAULT_MCP_STARTUP_TIMEOUT = 30.0
DEFAULT_MCP_REQUEST_TIMEOUT = 30.0

DEFAULT_GEMINI_TIMEOUT_SECONDS = 45.0
DEFAULT_GEMINI_MAX_RETRIES = 3
DEFAULT_GEMINI_MIN_RETRY_BACKOFF_SECONDS = 1.0

DEFAULT_PHOENIX_READ_TIMEOUT_SECONDS = 15.0
DEFAULT_PHOENIX_WRITE_TIMEOUT_SECONDS = 60.0
DEFAULT_PHOENIX_EXPERIMENT_TIMEOUT_SECONDS = 300.0

DEFAULT_GEMINI_CYCLE_TOKEN_BUDGET = 200_000
DEFAULT_GEMINI_INPUT_DOLLARS_PER_MILLION = 6.0
DEFAULT_GEMINI_OUTPUT_DOLLARS_PER_MILLION = 24.0


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
    cluster_trace_char_budget: int = DEFAULT_CLUSTER_TRACE_CHAR_BUDGET

    artifacts_dir: Path = field(default_factory=lambda: DEFAULT_ARTIFACTS_DIR)
    state_db_path: Path = field(default_factory=lambda: DEFAULT_STATE_DB)
    baseline_prompt_path: Path | None = None

    dashboard_host: str = DEFAULT_DASHBOARD_HOST
    dashboard_port: int = DEFAULT_DASHBOARD_PORT

    mcp_enabled: bool = True
    mcp_npx_command: str = DEFAULT_MCP_NPX_COMMAND
    mcp_package: str = DEFAULT_MCP_PACKAGE
    mcp_startup_timeout: float = DEFAULT_MCP_STARTUP_TIMEOUT
    mcp_request_timeout: float = DEFAULT_MCP_REQUEST_TIMEOUT

    gemini_timeout_seconds: float = DEFAULT_GEMINI_TIMEOUT_SECONDS
    gemini_max_retries: int = DEFAULT_GEMINI_MAX_RETRIES
    gemini_min_retry_backoff_seconds: float = DEFAULT_GEMINI_MIN_RETRY_BACKOFF_SECONDS

    phoenix_read_timeout_seconds: float = DEFAULT_PHOENIX_READ_TIMEOUT_SECONDS
    phoenix_write_timeout_seconds: float = DEFAULT_PHOENIX_WRITE_TIMEOUT_SECONDS
    phoenix_experiment_timeout_seconds: float = DEFAULT_PHOENIX_EXPERIMENT_TIMEOUT_SECONDS

    gemini_cycle_token_budget: int = DEFAULT_GEMINI_CYCLE_TOKEN_BUDGET
    gemini_input_dollars_per_million: float = DEFAULT_GEMINI_INPUT_DOLLARS_PER_MILLION
    gemini_output_dollars_per_million: float = DEFAULT_GEMINI_OUTPUT_DOLLARS_PER_MILLION

    circuit_breaker_backoff_seconds: int = 900
    circuit_breaker_consecutive_failures: int = 3

    metrics_enabled: bool = False

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
            raise ConfigError(
                "Phoenix base URL not configured. "
                "Run `nengok init --phoenix-url <url>` or set PHOENIX_BASE_URL."
            )

        for path_key in ("artifacts_dir", "state_db_path", "baseline_prompt_path"):
            value = merged.get(path_key)
            if value is not None and not isinstance(value, Path):
                merged[path_key] = Path(str(value))

        config = cls(**merged)
        config.validate()
        return config

    def validate(self) -> None:
        """
        Reject any combination that will fail downstream.

        Run at the end of `load()` and re-runnable on its own for tests.
        Surfaces missing secrets, malformed URLs, unreadable files, and
        out-of-range thresholds as `ConfigError` with a copy-paste hint.
        """
        if not self.google_api_key:
            raise ConfigError(
                "GOOGLE_API_KEY is not set. "
                "Run `export GOOGLE_API_KEY=<your key>` or add "
                "`google_api_key = '<your key>'` to ~/.nengok/config.toml. "
                "Get a key at https://aistudio.google.com/app/apikey."
            )

        if not self.phoenix_base_url:
            raise ConfigError(
                "Phoenix base URL not configured. "
                "Run `nengok init --phoenix-url <url>` or set PHOENIX_BASE_URL."
            )

        parsed = urlparse(self.phoenix_base_url)
        if not parsed.scheme or not parsed.netloc:
            raise ConfigError(
                f"phoenix_base_url '{self.phoenix_base_url}' is not a valid URL. "
                "Expected a value like 'http://localhost:6006' or 'https://app.phoenix.arize.com'."
            )

        if not self.project_identifier:
            raise ConfigError(
                "phoenix_project_name (project_identifier) is empty. "
                "Set it via --project, NENGOK_PROJECT, or the config file."
            )

        if self.project_identifier == SAMPLE_AGENT_PROJECT_NAME:
            logger.warning(
                "project_identifier is set to the bundled sample agent project "
                "'%s'. If you are monitoring a real agent, override "
                "phoenix_project_name in ~/.nengok/config.toml.",
                SAMPLE_AGENT_PROJECT_NAME,
            )

        if self.baseline_prompt_path is not None:
            path = self.baseline_prompt_path
            if not path.exists():
                raise ConfigError(
                    f"baseline_prompt_path '{path}' does not exist. "
                    "Point it at a readable .md or .txt prompt file, or unset it."
                )
            if not path.is_file():
                raise ConfigError(f"baseline_prompt_path '{path}' is not a file.")
            if not os.access(path, os.R_OK):
                raise ConfigError(f"baseline_prompt_path '{path}' is not readable by the current user.")

        agent_runner = getattr(self, "agent_runner", None)
        if agent_runner:
            if ":" not in agent_runner or agent_runner.count(":") != 1:
                raise ConfigError(
                    f"agent_runner '{agent_runner}' is malformed. "
                    "Expected `module.path:ClassName` (e.g. "
                    "`nengok.runners.sample_agent_runner:SampleAgentRunner`)."
                )
            module_part, class_part = agent_runner.split(":", 1)
            if not module_part or not class_part:
                raise ConfigError(
                    f"agent_runner '{agent_runner}' is malformed. " "Expected `module.path:ClassName`."
                )

        for name, value, lo, hi in _range_checks(self):
            if not lo <= value <= hi:
                raise ConfigError(
                    f"{name}={value} is out of range. " f"Expected a value between {lo} and {hi}."
                )


def _read_config_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    section: dict[str, Any] = data.get("nengok", {})
    return section


def _read_env() -> dict[str, Any]:
    mapping = {
        "PHOENIX_BASE_URL": "phoenix_base_url",
        "PHOENIX_API_KEY": "phoenix_api_key",
        "GOOGLE_API_KEY": "google_api_key",
        "NENGOK_PROJECT": "project_identifier",
        "NENGOK_DIAGNOSER_MODEL": "diagnoser_model",
        "NENGOK_JUDGE_MODEL": "judge_model",
        "NENGOK_ARTIFACTS_DIR": "artifacts_dir",
        "NENGOK_STATE_DB": "state_db_path",
        "NENGOK_DASHBOARD_PORT": "dashboard_port",
        "NENGOK_BASELINE_PROMPT_PATH": "baseline_prompt_path",
        "NENGOK_MCP_ENABLED": "mcp_enabled",
        "NENGOK_MCP_NPX_COMMAND": "mcp_npx_command",
        "NENGOK_MCP_PACKAGE": "mcp_package",
    }
    out: dict[str, Any] = {}
    for env_key, config_key in mapping.items():
        value = os.environ.get(env_key)
        if value is None:
            continue
        if config_key == "dashboard_port":
            out[config_key] = int(value)
        elif config_key == "mcp_enabled":
            out[config_key] = _parse_bool(value)
        else:
            out[config_key] = value
    return out


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _range_checks(cfg: NengokConfig) -> list[tuple[str, float, float, float]]:
    """
    Return `(name, value, lower, upper)` tuples for every bounded knob.

    Each entry is checked against `lo <= value <= hi`. Bounds are wide
    enough that legitimate tuning passes, narrow enough that fat-finger
    typos (e.g. a 0.5-second Gemini timeout, a negative span limit) are
    rejected before the orchestrator starts.
    """
    return [
        ("span_limit", cfg.span_limit, 1, 10_000),
        ("min_cluster_size", cfg.min_cluster_size, 1, 1_000),
        ("regression_pass_threshold", cfg.regression_pass_threshold, 0.0, 1.0),
        ("golden_regression_limit", cfg.golden_regression_limit, 0.0, 1.0),
        ("dry_run_samples", cfg.dry_run_samples, 1, 100),
        ("cluster_trace_char_budget", cfg.cluster_trace_char_budget, 100, 1_000_000),
        ("dashboard_port", cfg.dashboard_port, 1, 65_535),
        ("mcp_startup_timeout", cfg.mcp_startup_timeout, 1.0, 600.0),
        ("mcp_request_timeout", cfg.mcp_request_timeout, 1.0, 600.0),
        ("gemini_timeout_seconds", cfg.gemini_timeout_seconds, 5.0, 600.0),
        ("gemini_max_retries", cfg.gemini_max_retries, 0, 10),
        ("gemini_min_retry_backoff_seconds", cfg.gemini_min_retry_backoff_seconds, 0.0, 60.0),
        ("phoenix_read_timeout_seconds", cfg.phoenix_read_timeout_seconds, 1.0, 600.0),
        ("phoenix_write_timeout_seconds", cfg.phoenix_write_timeout_seconds, 1.0, 600.0),
        ("phoenix_experiment_timeout_seconds", cfg.phoenix_experiment_timeout_seconds, 1.0, 3_600.0),
        ("gemini_cycle_token_budget", cfg.gemini_cycle_token_budget, 1_000, 10_000_000),
        ("gemini_input_dollars_per_million", cfg.gemini_input_dollars_per_million, 0.0, 1_000.0),
        ("gemini_output_dollars_per_million", cfg.gemini_output_dollars_per_million, 0.0, 1_000.0),
        ("circuit_breaker_backoff_seconds", cfg.circuit_breaker_backoff_seconds, 1, 86_400),
        ("circuit_breaker_consecutive_failures", cfg.circuit_breaker_consecutive_failures, 1, 100),
    ]
