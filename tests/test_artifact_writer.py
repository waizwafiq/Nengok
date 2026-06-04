"""ArtifactWriter on-disk shape tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from nengok.core.observer.redactor import DEFAULT_RULES, Redactor
from nengok.core.types import (
    Cluster,
    ClusterStatus,
    ExperimentResult,
    PromptProposal,
    RegressionTestCase,
    RootCauseHypothesis,
    Verification,
    VerificationOutcome,
)
from nengok.core.verifier.artifact_writer import ArtifactWriter


def _cluster() -> Cluster:
    now = datetime.now(UTC)
    return Cluster(
        cluster_id="schema-drift-on-flights",
        name="schema-drift-on-flights",
        description="Flights tool returns departure_time as int instead of string.",
        status=ClusterStatus.DIAGNOSED,
        member_span_ids=["s1", "s2", "s3"],
        exemplar_span_ids=["s1", "s2"],
        hypothesis=RootCauseHypothesis(
            summary="Flights API contract drifted.",
            expected_behavior="`departure_time` is an ISO-8601 string.",
            actual_behavior="`departure_time` is a UNIX epoch integer.",
            likely_cause="flights.search v3 contract change.",
            implicated_tools=["tool.flights.search"],
        ),
        created_at=now,
        updated_at=now,
    )


def _proposal() -> PromptProposal:
    return PromptProposal(
        cluster_id="schema-drift-on-flights",
        baseline_prompt="# Travel Planner\nYou plan trips.",
        proposed_prompt="# Travel Planner\nYou plan trips.\n\n## Guardrail\n`departure_time` is always a string.",
        rationale="Added an explicit guardrail naming the departure_time type.",
    )


def _verification(outcome: VerificationOutcome = VerificationOutcome.PASSED) -> Verification:
    return Verification(
        outcome=outcome,
        experiment=ExperimentResult(
            experiment_name="schema-drift-fix",
            experiment_id="exp-42",
            dataset_name="schema-drift-regression-v1",
            baseline_pass_rate=0.25,
            fix_pass_rate=1.0,
            golden_baseline_pass_rate=1.0,
            golden_fix_pass_rate=1.0,
        ),
    )


def _cases() -> list[RegressionTestCase]:
    return [
        RegressionTestCase(
            case_id=f"case-{i}",
            input={"query": f"trip {i}"},
            expected={"contains": "departure"},
            metadata={"source": "schema-drift-cluster"},
        )
        for i in range(3)
    ]


def test_write_creates_three_files_under_cluster_subdirectory(tmp_path: Path) -> None:
    writer = ArtifactWriter(root=tmp_path)
    cluster = _cluster()

    artifact = writer.write(
        cluster=cluster,
        cases=_cases(),
        proposal=_proposal(),
        verification=_verification(),
    )

    cluster_dir = tmp_path / cluster.cluster_id
    assert cluster_dir.is_dir()
    assert (cluster_dir / "prompt.md").is_file()
    assert (cluster_dir / "regression.json").is_file()
    assert (cluster_dir / "rca.md").is_file()
    assert artifact.cluster_id == cluster.cluster_id
    assert artifact.prompt_path.endswith("prompt.md")
    assert artifact.dataset_path.endswith("regression.json")
    assert artifact.rca_path.endswith("rca.md")


def test_prompt_md_contains_rationale_baseline_and_proposed_body(tmp_path: Path) -> None:
    writer = ArtifactWriter(root=tmp_path)
    cluster = _cluster()

    writer.write(
        cluster=cluster,
        cases=_cases(),
        proposal=_proposal(),
        verification=_verification(),
    )

    body = (tmp_path / cluster.cluster_id / "prompt.md").read_text(encoding="utf-8")
    assert "# Proposed prompt (Nengok)" in body
    assert "## Rationale" in body
    assert "Added an explicit guardrail" in body
    assert "## Baseline prompt" in body
    assert "You plan trips." in body
    assert "## Prompt body" in body
    assert "departure_time` is always a string" in body


def test_regression_json_is_valid_json_and_round_trips_to_cases(tmp_path: Path) -> None:
    writer = ArtifactWriter(root=tmp_path)
    cluster = _cluster()
    cases = _cases()

    writer.write(
        cluster=cluster,
        cases=cases,
        proposal=_proposal(),
        verification=_verification(),
    )

    payload = json.loads((tmp_path / cluster.cluster_id / "regression.json").read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    assert len(payload) == len(cases)
    assert {case["case_id"] for case in payload} == {c.case_id for c in cases}
    assert payload[0]["input"] == cases[0].input
    assert payload[0]["expected"] == cases[0].expected
    assert payload[0]["metadata"] == cases[0].metadata


def test_rca_md_carries_hypothesis_and_experiment_summary(tmp_path: Path) -> None:
    writer = ArtifactWriter(root=tmp_path)
    cluster = _cluster()

    writer.write(
        cluster=cluster,
        cases=_cases(),
        proposal=_proposal(),
        verification=_verification(),
    )

    rca = (tmp_path / cluster.cluster_id / "rca.md").read_text(encoding="utf-8")
    assert "# Root-cause analysis" in rca
    assert cluster.name in rca
    assert "## Summary" in rca
    assert "Flights API contract drifted." in rca
    assert "## Expected vs. observed" in rca
    assert "ISO-8601 string" in rca
    assert "UNIX epoch integer" in rca
    assert "## Experiment" in rca
    assert "Baseline pass rate: 25%" in rca
    assert "Fix pass rate: 100%" in rca


def test_rca_md_falls_back_when_hypothesis_is_missing(tmp_path: Path) -> None:
    writer = ArtifactWriter(root=tmp_path)
    cluster = _cluster().model_copy(update={"hypothesis": None})

    writer.write(
        cluster=cluster,
        cases=_cases(),
        proposal=_proposal(),
        verification=_verification(),
    )

    rca = (tmp_path / cluster.cluster_id / "rca.md").read_text(encoding="utf-8")
    assert "No hypothesis recorded." in rca
    assert "**Expected:** n/a" in rca


def test_write_redacts_secrets_in_prompt_and_rca(tmp_path: Path) -> None:
    writer = ArtifactWriter(root=tmp_path, redactor=Redactor(rules=list(DEFAULT_RULES)))
    cluster = _cluster().model_copy(
        update={
            "hypothesis": RootCauseHypothesis(
                summary="user@example.com hit the bug",
                expected_behavior="ok",
                actual_behavior="email user@example.com leaked",
                likely_cause="missing redaction",
                implicated_tools=["tool.x"],
            ),
        }
    )
    proposal = PromptProposal(
        cluster_id=cluster.cluster_id,
        baseline_prompt="contact: support@example.com",
        proposed_prompt="contact: support@example.com",
        rationale="user@example.com asked us to redact.",
    )

    writer.write(
        cluster=cluster,
        cases=_cases(),
        proposal=proposal,
        verification=_verification(),
    )

    prompt_text = (tmp_path / cluster.cluster_id / "prompt.md").read_text(encoding="utf-8")
    rca_text = (tmp_path / cluster.cluster_id / "rca.md").read_text(encoding="utf-8")
    assert "user@example.com" not in prompt_text
    assert "user@example.com" not in rca_text
    assert "support@example.com" not in prompt_text


def test_write_is_idempotent_across_repeat_calls(tmp_path: Path) -> None:
    writer = ArtifactWriter(root=tmp_path)
    cluster = _cluster()

    writer.write(
        cluster=cluster,
        cases=_cases(),
        proposal=_proposal(),
        verification=_verification(),
    )
    writer.write(
        cluster=cluster,
        cases=_cases(),
        proposal=_proposal(),
        verification=_verification(),
    )

    cluster_dir = tmp_path / cluster.cluster_id
    children = sorted(p.name for p in cluster_dir.iterdir())
    assert children == ["manifest.json", "prompt.md", "rca.md", "regression.json"]


def test_failed_verification_still_writes_full_artifact_bundle(tmp_path: Path) -> None:
    writer = ArtifactWriter(root=tmp_path)
    cluster = _cluster()

    artifact = writer.write(
        cluster=cluster,
        cases=_cases(),
        proposal=_proposal(),
        verification=_verification(VerificationOutcome.FAILED_REGRESSION),
    )

    assert artifact.verification.outcome is VerificationOutcome.FAILED_REGRESSION
    for filename in ("prompt.md", "regression.json", "rca.md"):
        assert (tmp_path / cluster.cluster_id / filename).is_file()


def test_returned_fix_artifact_paths_resolve_to_disk(tmp_path: Path) -> None:
    writer = ArtifactWriter(root=tmp_path)
    cluster = _cluster()

    artifact = writer.write(
        cluster=cluster,
        cases=_cases(),
        proposal=_proposal(),
        verification=_verification(),
    )

    assert Path(artifact.prompt_path).is_file()
    assert Path(artifact.dataset_path).is_file()
    assert Path(artifact.rca_path).is_file()
