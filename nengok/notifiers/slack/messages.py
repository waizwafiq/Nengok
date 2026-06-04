"""Block Kit message builders for the Slack notifier.

All builders work from FixProposedEvent fields only — no raw cluster objects,
no artifact bodies. The build_error_blocks helper is also used by the inbound
action handlers to surface validation failures without a round-trip to Slack
modal.
"""

from __future__ import annotations

import json

from nengok.notifiers.events import FixProposedEvent


def build_fix_proposed_blocks(
    event: FixProposedEvent,
    *,
    dry_run: bool,
    dashboard_base_url: str | None,
) -> list[dict]:
    """Build the initial fix-ready notification message blocks."""
    exp = event.experiment_summary
    dashboard_url = (
        f"{dashboard_base_url.rstrip('/')}/clusters/{event.cluster_id}" if dashboard_base_url else None
    )

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Nengok fix ready for review"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Cluster:* {event.cluster_name}"},
                {"type": "mrkdwn", "text": f"*ID:* `{event.cluster_id}`"},
                {"type": "mrkdwn", "text": f"*Status:* `{event.status}`"},
            ],
        },
    ]

    if event.hypothesis_summary:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": event.hypothesis_summary},
            }
        )

    blocks.append(
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Baseline pass rate:* {exp.baseline_pass_rate:.0%}"},
                {"type": "mrkdwn", "text": f"*Fix pass rate:* {exp.fix_pass_rate:.0%}"},
                {"type": "mrkdwn", "text": f"*Golden baseline:* {exp.golden_baseline_pass_rate:.0%}"},
                {"type": "mrkdwn", "text": f"*Golden fix:* {exp.golden_fix_pass_rate:.0%}"},
            ],
        }
    )

    if dry_run:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": ":warning: *Notifier dry-run mode* — approval buttons are disabled. Use the dashboard.",
                    }
                ],
            }
        )
        if dashboard_url:
            blocks.append(_dashboard_button(dashboard_url))
        return blocks

    action_value = json.dumps({"cluster_id": event.cluster_id, "event_kind": event.event_kind})
    action_elements: list[dict] = []
    if dashboard_url:
        action_elements.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "View dashboard"},
                "url": dashboard_url,
            }
        )
    action_elements += [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Approve"},
            "action_id": "nengok_approve_fix",
            "value": action_value,
            "style": "primary",
        },
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Reject"},
            "action_id": "nengok_reject_fix",
            "value": action_value,
            "style": "danger",
        },
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Dismiss"},
            "action_id": "nengok_dismiss_fix",
            "value": action_value,
        },
    ]
    blocks.append({"type": "actions", "elements": action_elements})
    return blocks


def build_decision_blocks(
    *,
    cluster_name: str,
    decision: str,
    reviewer: str,
    reason: str | None,
    dashboard_url: str | None,
) -> list[dict]:
    """Build the post-decision update message blocks (no action buttons)."""
    decision_text = f"*{decision.capitalize()}* by {reviewer}"
    if reason:
        decision_text += f"\n_Reason:_ {reason}"

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Nengok fix {decision}"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Cluster:* {cluster_name}"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": decision_text},
        },
    ]
    if dashboard_url:
        blocks.append(_dashboard_button(dashboard_url))
    return blocks


def build_error_blocks(*, message: str, dashboard_url: str | None) -> list[dict]:
    """Build an error state message (used by action handlers on validation failure)."""
    blocks: list[dict] = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f":x: {message}"},
        },
    ]
    if dashboard_url:
        blocks.append(_dashboard_button(dashboard_url))
    return blocks


def _dashboard_button(url: str) -> dict:
    return {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "View dashboard"},
                "url": url,
            }
        ],
    }
