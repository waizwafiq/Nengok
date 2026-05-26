"""Unit tests for the PII redactor and its integration with the clusterer."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from nengok.config import NengokConfig
from nengok.core.diagnoser.clusterer import Clusterer
from nengok.core.observer.redactor import (
    DEFAULT_RULE_NAMES,
    DEFAULT_RULES,
    RedactionRule,
    Redactor,
)
from nengok.core.types import AnomalousSpan, AnomalySignal, TraceSpan


def _redactor(rule_names: list[str] | None = None) -> Redactor:
    if rule_names is None:
        return Redactor(rules=DEFAULT_RULES)
    selected = [rule for rule in DEFAULT_RULES if rule.name in rule_names]
    return Redactor(rules=selected)


def test_email_rule_scrubs_plain_address() -> None:
    r = _redactor(["email"])
    assert r.redact("contact mwaiz@example.com today") == "contact <redacted-email> today"


def test_email_rule_leaves_non_matches_alone() -> None:
    r = _redactor(["email"])
    assert r.redact("ping me at #channel today") == "ping me at #channel today"


def test_google_api_key_rule_matches_aiza_prefix() -> None:
    r = _redactor(["google_api_key"])
    text = "key=AIzaSyD1234567890abcdefghijklmnopqrstuvwx"
    out = r.redact(text)
    assert "AIzaSyD1234" not in out
    assert "<redacted-google-api-key>" in out


def test_google_api_key_does_not_match_short_lookalike() -> None:
    r = _redactor(["google_api_key"])
    assert r.redact("AIzaShort") == "AIzaShort"


def test_aws_key_rule_matches_akia_prefix() -> None:
    r = _redactor(["aws_access_key"])
    assert "<redacted-aws-key>" in r.redact("AKIAIOSFODNN7EXAMPLE in logs")


def test_bearer_token_rule_strips_token_keeps_keyword() -> None:
    r = _redactor(["bearer_token"])
    assert r.redact("Authorization: Bearer abcdef.ghijkl_mnop") == ("Authorization: Bearer <redacted-token>")


def test_password_field_rule_scrubs_value_keeps_key() -> None:
    r = _redactor(["password_field"])
    assert r.redact("password=hunter2") == "password=<redacted>"
    assert r.redact("Secret: topsecret") == "Secret=<redacted>"


def test_credit_card_rule_matches_16_digit_block() -> None:
    r = _redactor(["credit_card"])
    out = r.redact("card 4111-1111-1111-1111 on file")
    assert "4111" not in out
    assert "<redacted-cc>" in out


def test_credit_card_does_not_match_short_number_runs() -> None:
    r = _redactor(["credit_card"])
    assert r.redact("order 12345 ready") == "order 12345 ready"


def test_ssn_rule_matches_us_ssn_shape() -> None:
    r = _redactor(["ssn"])
    assert r.redact("SSN 123-45-6789 verified") == "SSN <redacted-ssn> verified"


def test_phone_rule_matches_common_us_formats() -> None:
    r = _redactor(["us_phone"])
    for raw in ("+1 415 555 0199", "(415) 555-0199", "415.555.0199"):
        assert "<redacted-phone>" in r.redact(raw), raw


def test_ipv4_rule_replaces_dotted_quad() -> None:
    r = _redactor(["ipv4"])
    assert r.redact("client 192.168.1.42 connected") == "client <redacted-ipv4> connected"


def test_ipv6_rule_replaces_compressed_address() -> None:
    r = _redactor(["ipv6"])
    out = r.redact("peer 2001:db8::1 reachable")
    assert "<redacted-ipv6>" in out


def test_redact_none_returns_empty_string() -> None:
    assert Redactor(rules=DEFAULT_RULES).redact(None) == ""
    assert Redactor(rules=DEFAULT_RULES).redact("") == ""


def test_default_rule_names_matches_default_rules_in_order() -> None:
    derived = [rule.name for rule in DEFAULT_RULES]
    assert derived == DEFAULT_RULE_NAMES


def test_from_config_disables_redaction_when_flag_off(tmp_config: NengokConfig) -> None:
    config = replace(tmp_config, redaction_enabled=False)
    redactor = Redactor.from_config(config)
    assert redactor.redact("mwaiz@example.com") == "mwaiz@example.com"


def test_from_config_honors_default_rule_subset(tmp_config: NengokConfig) -> None:
    config = replace(tmp_config, redaction_default_rules=["email"])
    redactor = Redactor.from_config(config)
    assert "<redacted-email>" in redactor.redact("mwaiz@example.com")
    raw_card = "card 4111-1111-1111-1111 on file"
    assert redactor.redact(raw_card) == raw_card


def test_from_config_appends_user_rules(tmp_config: NengokConfig) -> None:
    config = replace(
        tmp_config,
        redaction_rules=[
            {
                "name": "tenant_id",
                "pattern": r"tenant=[A-Za-z0-9]+",
                "replacement": "tenant=<redacted>",
            },
        ],
    )
    redactor = Redactor.from_config(config)
    assert redactor.redact("tenant=acme42 and mwaiz@example.com") == (
        "tenant=<redacted> and <redacted-email>"
    )


def test_from_config_uses_custom_callable(tmp_config: NengokConfig) -> None:
    config = replace(
        tmp_config,
        redactor_callable="tests.fixtures_redactor:upper_redactor",
    )
    redactor = Redactor.from_config(config)
    assert redactor.redact("mwaiz@example.com") == "MWAIZ@EXAMPLE.COM"


def test_custom_callable_with_bad_path_raises() -> None:
    bad_rule = RedactionRule(name="x", pattern="x", replacement="y")
    assert bad_rule.pattern == "x"
    from nengok.core.observer.redactor import _load_callable_redactor

    with pytest.raises(ValueError, match="malformed"):
        _load_callable_redactor("not-a-dotted-path")

    with pytest.raises(ValueError, match="did not resolve"):
        _load_callable_redactor("tests.fixtures_redactor:missing_attr")


def _anomaly_with_pii() -> AnomalousSpan:
    return AnomalousSpan(
        span=TraceSpan(
            span_id="s1",
            trace_id="t1",
            name="agent.respond",
            status_code="ERROR",
            latency_ms=200.0,
            input_value="user mwaiz@example.com paid with 4111-1111-1111-1111",
            output_value="Stored AIzaSyD1234567890abcdefghijklmnopqrstuvwx",
            attributes={},
            annotations={},
        ),
        signals=[AnomalySignal.ERROR_STATUS],
    )


def test_clusterer_redacts_span_text_in_gemini_prompt(tmp_config: NengokConfig) -> None:
    captured: dict[str, str] = {}

    def fake_gemini(prompt: str) -> str:
        captured["prompt"] = prompt
        return json.dumps(
            {
                "clusters": [
                    {
                        "name": "pii-cluster",
                        "description": "PII leak shape",
                        "member_span_ids": ["s1"],
                    }
                ]
            }
        )

    Clusterer(config=tmp_config, gemini_call=fake_gemini).cluster([_anomaly_with_pii()])

    prompt_text = captured["prompt"]
    assert "mwaiz@example.com" not in prompt_text
    assert "4111-1111-1111-1111" not in prompt_text
    assert "AIzaSyD1234567890abcdefghijklmnopqrstuvwx" not in prompt_text
    assert "<redacted-email>" in prompt_text
    assert "<redacted-cc>" in prompt_text
    assert "<redacted-google-api-key>" in prompt_text


def test_clusterer_skips_redaction_when_disabled(tmp_config: NengokConfig) -> None:
    disabled = replace(tmp_config, redaction_enabled=False)
    captured: dict[str, str] = {}

    def fake_gemini(prompt: str) -> str:
        captured["prompt"] = prompt
        return json.dumps(
            {
                "clusters": [
                    {
                        "name": "raw",
                        "description": "raw",
                        "member_span_ids": ["s1"],
                    }
                ]
            }
        )

    Clusterer(config=disabled, gemini_call=fake_gemini).cluster([_anomaly_with_pii()])

    assert "mwaiz@example.com" in captured["prompt"]
