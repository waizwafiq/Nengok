"""Backend-aware google-genai client factory (AI Studio vs Vertex AI)."""

from __future__ import annotations

import pytest

pytest.importorskip(
    "google.genai",
    reason="google-genai not installed; the factory tests stub google.genai.Client.",
)

from nengok.config import NengokConfig
from nengok.errors import MissingApiKeyError
from nengok.utils.genai_client import build_genai_client, build_genai_client_from_env

_GOOGLE_ENV = (
    "GOOGLE_API_KEY",
    "GOOGLE_GENAI_USE_VERTEXAI",
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_CLOUD_LOCATION",
)


def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _GOOGLE_ENV:
        monkeypatch.delenv(key, raising=False)


def _install_recording_client(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Replace google.genai.Client with a fake that records its kwargs."""
    captured: dict[str, object] = {}

    class _Client:
        def __init__(self, **kwargs: object) -> None:
            captured.clear()
            captured.update(kwargs)

    monkeypatch.setattr("google.genai.Client", _Client, raising=False)
    return captured


def _config(**overrides: object) -> NengokConfig:
    base: dict[str, object] = {"phoenix_base_url": "http://localhost:6006"}
    base.update(overrides)
    return NengokConfig(**base)  # type: ignore[arg-type]


def test_factory_ai_studio_passes_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate(monkeypatch)
    captured = _install_recording_client(monkeypatch)
    build_genai_client(_config(gemini_use_vertex=False, google_api_key="AIzaKEY"), role="Clusterer")
    assert captured == {"api_key": "AIzaKEY"}


def test_factory_ai_studio_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate(monkeypatch)
    monkeypatch.setenv("GOOGLE_API_KEY", "AIzaENV")
    captured = _install_recording_client(monkeypatch)
    build_genai_client(_config(gemini_use_vertex=False, google_api_key=None), role="Clusterer")
    assert captured == {"api_key": "AIzaENV"}


def test_factory_ai_studio_missing_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate(monkeypatch)
    _install_recording_client(monkeypatch)
    with pytest.raises(MissingApiKeyError, match="Clusterer"):
        build_genai_client(_config(gemini_use_vertex=False, google_api_key=None), role="Clusterer")


def test_factory_vertex_passes_project_location(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate(monkeypatch)
    captured = _install_recording_client(monkeypatch)
    build_genai_client(
        _config(gemini_use_vertex=True, vertex_project="proj", vertex_location="europe-west4"),
        role="Hypothesizer",
    )
    assert captured == {"vertexai": True, "project": "proj", "location": "europe-west4"}


def test_factory_vertex_default_location_global(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate(monkeypatch)
    captured = _install_recording_client(monkeypatch)
    build_genai_client(
        _config(gemini_use_vertex=True, vertex_project="proj", vertex_location=""),
        role="Hypothesizer",
    )
    assert captured["location"] == "global"


def test_factory_vertex_project_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate(monkeypatch)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "env-proj")
    captured = _install_recording_client(monkeypatch)
    build_genai_client(_config(gemini_use_vertex=True, vertex_project=None), role="Hypothesizer")
    assert captured["vertexai"] is True
    assert captured["project"] == "env-proj"


def test_factory_vertex_missing_project_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate(monkeypatch)
    _install_recording_client(monkeypatch)
    with pytest.raises(MissingApiKeyError, match="Vertex"):
        build_genai_client(_config(gemini_use_vertex=True, vertex_project=None), role="Hypothesizer")


def test_env_helper_selects_vertex(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate(monkeypatch)
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    captured = _install_recording_client(monkeypatch)
    build_genai_client_from_env()
    assert captured == {"vertexai": True, "project": "p", "location": "us-central1"}


def test_env_helper_selects_ai_studio(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate(monkeypatch)
    monkeypatch.setenv("GOOGLE_API_KEY", "AIzaENV")
    captured = _install_recording_client(monkeypatch)
    build_genai_client_from_env()
    assert captured == {"api_key": "AIzaENV"}
