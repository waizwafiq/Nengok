"""One-shot demo annotator: score seeded travel-planner spans so the
rule-based anomaly filter has a LOW_EVAL_SCORE signal to fire on."""

import re

from dotenv import load_dotenv
from phoenix.client import Client

from nengok.config import NengokConfig
from nengok.phoenix.client import PhoenixWrapper

load_dotenv(r"d:\Hackathons\Google Cloud Rapid Agent 2026\nengok-codebase\.env")

CATALOG = ("Park Hyatt Tokyo", "Cerulean Tower Tokyu")
TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\b")

cfg = NengokConfig.load()
wrapper = PhoenixWrapper(cfg)
spans = wrapper.get_spans(project_identifier="travel-planner-agent", limit=200, with_annotations=False)
print(f"pulled {len(spans)} spans")

client = Client(base_url=cfg.phoenix_base_url)
n_fail = n_pass = 0
for s in spans:
    sid = getattr(s, "span_id", None) or getattr(s, "id", None)
    out = getattr(s, "output_value", None) or ""
    if not sid or not out:
        continue
    reasons = []
    if not TIME_RE.search(out):
        reasons.append("no HH:MM departure time")
    if re.search(r"[\"']hour[\"']", out) or re.search(r"[\"']minute[\"']", out):
        reasons.append("raw schema dict leaked")
    if re.search(r"hotel", out, re.IGNORECASE) and not any(h in out for h in CATALOG):
        reasons.append("hotel names not in catalog")
    score = 0.0 if reasons else 1.0
    label = "fail" if reasons else "pass"
    client.spans.add_span_annotation(
        annotation_name="itinerary_contract_check",
        span_id=sid,
        annotator_kind="CODE",
        label=label,
        score=score,
    )
    if reasons:
        n_fail += 1
    else:
        n_pass += 1
print(f"annotated: {n_fail} fail, {n_pass} pass")
