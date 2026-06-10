"""CrossAgentLinker unit tests plus the store roundtrip for links."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from nengok.config import NengokConfig
from nengok.core.diagnoser.cross_agent import CrossAgentLinker, _candidate_pairs
from nengok.core.diagnoser.hypothesizer import _build_diagnoser_prompt
from nengok.core.observer.redactor import Redactor
from nengok.core.types import Cluster, ClusterStatus, RootCauseHypothesis
from nengok.state.store import StateStore


def _cluster(
    cluster_id: str,
    name: str,
    project: str | None,
    *,
    signals: list[str] | None = None,
    tools: list[str] | None = None,
) -> Cluster:
    now = datetime.now(UTC)
    hypothesis = None
    if tools is not None:
        hypothesis = RootCauseHypothesis(
            summary=f"summary for {name}",
            expected_behavior="e",
            actual_behavior="a",
            likely_cause="c",
            implicated_tools=tools,
        )
    return Cluster(
        cluster_id=cluster_id,
        name=name,
        description="d",
        status=ClusterStatus.DIAGNOSED,
        member_span_ids=[f"s-{cluster_id}"],
        exemplar_span_ids=[f"s-{cluster_id}"],
        hypothesis=hypothesis,
        created_at=now,
        updated_at=now,
        signals=signals or [],
        project=project,
    )


def _verdict(linked: bool, confidence: float) -> str:
    return json.dumps({"linked": linked, "confidence": confidence, "rationale": "shared flights API"})


def test_candidate_pairs_require_distinct_projects() -> None:
    same_project = [
        _cluster("a", "flights-drift", "travel", signals=["error_status"]),
        _cluster("b", "flights-drift-two", "travel", signals=["error_status"]),
    ]
    assert _candidate_pairs(same_project) == []

    cross_project = [
        _cluster("a", "flights-drift", "travel", signals=["error_status"]),
        _cluster("b", "qa-flights-failure", "qa", signals=["error_status"]),
    ]
    pairs = _candidate_pairs(cross_project)
    assert len(pairs) == 1


def test_candidate_pairs_skip_unrelated_clusters() -> None:
    clusters = [
        _cluster("a", "hotels-timeout", "travel", signals=["high_latency"]),
        _cluster("b", "citation-style", "qa", signals=["low_eval_score"]),
    ]
    assert _candidate_pairs(clusters) == []


def test_judge_confirms_link(tmp_config: NengokConfig) -> None:
    clusters = [
        _cluster("a", "flights-drift", "travel", signals=["error_status"], tools=["tool.flights"]),
        _cluster("b", "qa-flights-broken", "qa", signals=["error_status"], tools=["tool.flights"]),
    ]

    linker = CrossAgentLinker(config=tmp_config, gemini_call=lambda _: _verdict(True, 0.9))
    links = linker.link(clusters)

    assert len(links) == 1
    assert {links[0].cluster_id_a, links[0].cluster_id_b} == {"a", "b"}
    assert links[0].rationale == "shared flights API"


def test_judge_denial_and_low_confidence_drop_the_pair(tmp_config: NengokConfig) -> None:
    clusters = [
        _cluster("a", "flights-drift", "travel", signals=["error_status"]),
        _cluster("b", "qa-flights-broken", "qa", signals=["error_status"]),
    ]

    denied = CrossAgentLinker(config=tmp_config, gemini_call=lambda _: _verdict(False, 0.99))
    assert denied.link(clusters) == []

    low = CrossAgentLinker(config=tmp_config, gemini_call=lambda _: _verdict(True, 0.4))
    assert low.link(clusters) == []


def test_max_pairs_cap_limits_judge_calls(tmp_path: Path) -> None:
    config = NengokConfig.load(
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://localhost:6006",
        google_api_key="AIzaTEST",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
        cluster_link_max_pairs=1,
    )
    clusters = [
        _cluster("a1", "flights-drift", "travel", signals=["error_status"]),
        _cluster("a2", "flights-stall", "travel", signals=["error_status"]),
        _cluster("b1", "qa-flights-broken", "qa", signals=["error_status"]),
    ]
    calls: list[str] = []

    def fake_judge(prompt: str) -> str:
        calls.append(prompt)
        return _verdict(True, 0.9)

    linker = CrossAgentLinker(config=config, gemini_call=fake_judge)
    links = linker.link(clusters)

    assert len(calls) == 1
    assert len(links) == 1


def test_store_link_roundtrip_orders_canonically_and_dedups(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    store.upsert_cluster(_cluster("zzz", "flights-drift", "travel"))
    store.upsert_cluster(_cluster("aaa", "qa-flights-broken", "qa"))

    first = store.insert_cluster_link(
        cluster_id_a="zzz", cluster_id_b="aaa", confidence=0.9, rationale="shared flights API"
    )
    assert first is not None

    duplicate = store.insert_cluster_link(
        cluster_id_a="aaa", cluster_id_b="zzz", confidence=0.8, rationale="again"
    )
    assert duplicate is None

    links = store.list_cluster_links("zzz")
    assert len(links) == 1
    assert links[0]["cluster_id_a"] == "aaa"
    assert links[0]["cluster_id_b"] == "zzz"
    assert links[0]["linked_cluster_id"] == "aaa"
    assert links[0]["linked_name"] == "qa-flights-broken"
    assert links[0]["linked_project"] == "qa"


def test_diagnoser_prompt_includes_sibling_summary(tmp_config: NengokConfig) -> None:
    cluster = _cluster("a", "flights-drift", "travel", signals=["error_status"])
    prompt = _build_diagnoser_prompt(
        cluster=cluster,
        exemplars=[],
        current_prompt="BASE",
        char_budget=2000,
        redactor=Redactor.from_config(tmp_config),
        linked_summaries=["[qa / qa-flights-broken] flights API changed its schema"],
    )
    assert "shared upstream cause" in prompt
    assert "flights API changed its schema" in prompt
