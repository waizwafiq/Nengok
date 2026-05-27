"""Tests for the retrieval-augmented QA sample agent."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nengok.runners import AgentRunner
from sample_agent.qa_agent.agent import (
    CORPUS,
    QAAgent,
    _swap_attributions,
    answer_question,
    retrieve,
)

GOLDEN_PATH = Path(__file__).resolve().parents[1] / "golden_dataset" / "qa_golden.json"


def test_qa_agent_name_is_stable() -> None:
    assert QAAgent().name == "qa-agent"


def test_qa_agent_satisfies_runner_protocol() -> None:
    assert isinstance(QAAgent(), AgentRunner)


def test_retrieve_returns_matching_snippets_for_known_question() -> None:
    snippets = retrieve("What is Nengok?", drop_context=False)
    ids = [sid for sid, _ in snippets]
    assert "nengok-overview" in ids


def test_retrieve_returns_empty_when_context_dropped() -> None:
    assert retrieve("What is Nengok?", drop_context=True) == []


def test_swap_attributions_rotates_ids_by_one() -> None:
    snippets = [
        ("snippet-a", "body-A"),
        ("snippet-b", "body-B"),
        ("snippet-c", "body-C"),
    ]
    rotated = _swap_attributions(snippets)
    assert [sid for sid, _ in rotated] == ["snippet-b", "snippet-c", "snippet-a"]
    assert [body for _, body in rotated] == ["body-A", "body-B", "body-C"]


def test_swap_attributions_no_op_on_one_snippet() -> None:
    snippets = [("only-snippet", "body")]
    assert _swap_attributions(snippets) == snippets


def test_corpus_includes_anchored_topics() -> None:
    ids = {sid for sid, _ in CORPUS}
    for required in (
        "nengok-overview",
        "phoenix-overview",
        "human-in-the-loop",
        "data-egress",
        "evaluator-policy",
    ):
        assert required in ids


def test_hallucination_failure_appends_directive_to_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip(
        "google.genai",
        reason="google-genai not installed; this test stubs google.genai.Client.",
    )
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key-for-test")
    captured: dict[str, str] = {}

    class _StubClient:
        def __init__(self, *, api_key: str) -> None:
            self.api_key = api_key
            self.models = self

        def generate_content(self, **kwargs):
            text = kwargs["contents"][0]["parts"][0]["text"]
            captured["prompt"] = text

            class _Response:
                text = "stub-answer"
                usage_metadata = None

            return _Response()

    monkeypatch.setattr("google.genai.Client", _StubClient, raising=False)

    answer_question("What is Nengok?", failure="hallucination")

    assert "Override" in captured["prompt"]
    assert "prior knowledge" in captured["prompt"]


def test_wrong_attribution_failure_rotates_snippet_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip(
        "google.genai",
        reason="google-genai not installed; this test stubs google.genai.Client.",
    )
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key-for-test")
    captured: dict[str, str] = {}

    class _StubClient:
        def __init__(self, *, api_key: str) -> None:
            self.api_key = api_key
            self.models = self

        def generate_content(self, **kwargs):
            text = kwargs["contents"][0]["parts"][0]["text"]
            captured["prompt"] = text

            class _Response:
                text = "stub-answer"
                usage_metadata = None

            return _Response()

    monkeypatch.setattr("google.genai.Client", _StubClient, raising=False)

    question = "How does Nengok handle Phoenix observability?"
    baseline = answer_question(question, failure="none")
    rotated = answer_question(question, failure="wrong_attribution")

    baseline_ids = [sid for sid, _ in baseline["snippets"]]
    rotated_ids = [sid for sid, _ in rotated["snippets"]]

    if len(baseline_ids) >= 2:
        assert baseline_ids != rotated_ids
        assert sorted(baseline_ids) == sorted(rotated_ids)


def test_golden_dataset_loads_and_pins_snippet_ids() -> None:
    payload = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))

    assert payload["name"] == "qa_agent_golden"
    assert payload["version"] == 1

    cases = payload["cases"]
    assert len(cases) == 5

    known_ids = {sid for sid, _ in CORPUS}
    for case in cases:
        assert case["case_id"].startswith("qa-")
        assert "question" in case["input"]
        cited = case["expected"]["cites_snippet"]
        assert cited in known_ids


def test_qa_agent_run_dispatches_to_answer_question(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key-for-test")
    called: dict[str, object] = {}

    def stub_answer(question: str, *, prompt: str | None = None, failure: str = "none") -> dict:
        called["question"] = question
        called["prompt"] = prompt
        called["failure"] = failure
        return {"answer": "stub"}

    monkeypatch.setattr("sample_agent.qa_agent.agent.answer_question", stub_answer)

    QAAgent().run({"question": "What is Nengok?", "failure": "hallucination"}, "PROMPT-V2")

    assert called["question"] == "What is Nengok?"
    assert called["prompt"] == "PROMPT-V2"
    assert called["failure"] == "hallucination"


def test_qa_agent_run_falls_back_to_query_key(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    def stub_answer(question: str, *, prompt: str | None = None, failure: str = "none") -> dict:
        called["question"] = question
        return {"answer": "stub"}

    monkeypatch.setattr("sample_agent.qa_agent.agent.answer_question", stub_answer)
    QAAgent().run({"query": "What is Phoenix?"}, "p")

    assert called["question"] == "What is Phoenix?"


def test_qa_agent_run_normalizes_unknown_failure_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    def stub_answer(question: str, *, prompt: str | None = None, failure: str = "none") -> dict:
        called["failure"] = failure
        return {"answer": "stub"}

    monkeypatch.setattr("sample_agent.qa_agent.agent.answer_question", stub_answer)
    QAAgent().run({"question": "anything", "failure": "definitely-not-a-mode"}, "p")

    assert called["failure"] == "none"


def test_corpus_supplies_at_least_two_matching_snippets_for_phoenix_question() -> None:
    snippets = retrieve("How does Nengok handle Phoenix observability?", drop_context=False)
    assert len(snippets) >= 2, (
        "wrong_attribution rotation needs at least two matching snippets to be observable; " f"got {snippets}"
    )
