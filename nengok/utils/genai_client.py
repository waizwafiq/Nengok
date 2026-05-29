"""
Backend-aware construction of the `google-genai` client.

`google-genai` exposes a single `genai.Client` that talks to either
Google AI Studio (`api_key=...`) or Vertex AI (`vertexai=True,
project=..., location=...`, authenticating via Application Default
Credentials, no API key). Centralizing construction here keeps the
backend choice in one place so every diagnoser/fixer stage and the
health probe agree, and so Nengok's config (not ambient SDK env vars)
stays authoritative.

The Vertex branch always passes `vertexai=True` explicitly rather than
relying on the SDK's own `GOOGLE_GENAI_USE_VERTEXAI` auto-detection, so
the selected backend is unambiguous. The AI Studio branch passes only
`api_key`, matching the prior call sites; in normal use the two cannot
diverge because `gemini_use_vertex` is itself read from
`GOOGLE_GENAI_USE_VERTEXAI` in `NengokConfig._read_env`.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from nengok.errors import MissingApiKeyError, OptionalDependencyError

if TYPE_CHECKING:
    from nengok.config import NengokConfig

# Fallback when neither config nor GOOGLE_CLOUD_LOCATION supplies a region.
# Mirrors nengok.config.DEFAULT_VERTEX_LOCATION; kept local to avoid importing
# config at runtime (genai_client is imported from inside config-bearing stages).
_DEFAULT_VERTEX_LOCATION = "global"
_VERTEX_TRUTHY = {"1", "true", "yes", "on"}


def _import_genai() -> Any:
    try:
        from google import genai
    except ImportError as exc:
        raise OptionalDependencyError(
            "google-genai is not installed but is required to call Gemini.",
            install_hint="pip install nengok[gemini]",
        ) from exc
    return genai


def build_genai_client(config: NengokConfig, *, role: str) -> Any:
    """
    Return a `google-genai` client wired for the configured backend.

    Vertex mode requires a GCP project (``vertex_project`` or
    ``GOOGLE_CLOUD_PROJECT``) and authenticates with Application Default
    Credentials. AI Studio mode requires ``GOOGLE_API_KEY`` (config or
    env). ``role`` names the calling stage so a missing-credential error
    points back at the knob the user actually turned.
    """
    genai = _import_genai()

    if config.gemini_use_vertex:
        project = config.vertex_project or os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not project:
            raise MissingApiKeyError(
                f"{role} is configured for Vertex AI but no GCP project is set. "
                'Set `vertex_project = "..."` in ~/.nengok/config.toml or export '
                "GOOGLE_CLOUD_PROJECT, then run `gcloud auth application-default login`.",
                role=role,
            )
        location = (
            config.vertex_location or os.environ.get("GOOGLE_CLOUD_LOCATION") or _DEFAULT_VERTEX_LOCATION
        )
        return genai.Client(vertexai=True, project=project, location=location)

    api_key = config.google_api_key or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise MissingApiKeyError(
            f"{role} needs a Gemini API key. Set `GOOGLE_API_KEY` in your "
            'environment (or `.env`), or write `google_api_key = "..."` into '
            "`~/.nengok/config.toml`. Get a key at https://aistudio.google.com/app/apikey.",
            role=role,
        )
    return genai.Client(api_key=api_key)


def build_genai_client_from_env() -> Any:
    """
    Construct a client from SDK-standard env vars (for the sample agents).

    The bundled sample agents have no ``NengokConfig``. They honor the
    same ``GOOGLE_GENAI_USE_VERTEXAI`` / ``GOOGLE_CLOUD_PROJECT`` /
    ``GOOGLE_CLOUD_LOCATION`` env vars the SDK reads, but pass the backend
    selection explicitly so behavior matches :func:`build_genai_client`.
    The AI Studio branch reads ``GOOGLE_API_KEY`` directly (``KeyError``
    if unset), preserving the agents' previous behavior.
    """
    genai = _import_genai()

    if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").strip().lower() in _VERTEX_TRUTHY:
        return genai.Client(
            vertexai=True,
            project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
            location=os.environ.get("GOOGLE_CLOUD_LOCATION") or _DEFAULT_VERTEX_LOCATION,
        )
    return genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
