"""Slack inbound event route — mounted at /slack/events (outside /api/v1).

Auth boundary: Slack request signature verification only (handled by Bolt).
Dashboard bearer tokens do not authenticate Slack routes.
Rate limiting under /api/v1 is intentionally bypassed for Slack callbacks.

Action handler sequencing:
  Approve  — ack(), resolve identity, validate, record, chat.update
  Reject   — ack(), dry-run check, views.open (no DB/API calls before views.open)
  Dismiss  — ack(), dry-run check, views.open
  view_submission — ack(), re-check dry-run, resolve identity, validate, record, chat.update
"""

from __future__ import annotations

import contextlib
import json
import logging

from fastapi import APIRouter, Request

from nengok.config import NengokConfig
from nengok.core.types import ClusterStatus
from nengok.state.store import StateStore

logger = logging.getLogger(__name__)

_DECISION_TO_STATUS = {
    "approved": ClusterStatus.APPROVED,
    "rejected": ClusterStatus.REJECTED,
    "dismissed": ClusterStatus.DISMISSED,
}


def create_slack_router(config: NengokConfig) -> APIRouter:
    """Return a router with /slack/events mounted. Returns empty router if Slack is not configured."""
    router = APIRouter(tags=["slack"])

    if "slack" not in config.notifiers:
        return router

    if not config.slack_bot_token or not config.slack_signing_secret:
        logger.warning(
            "Slack is in notifiers list but SLACK_BOT_TOKEN or SLACK_SIGNING_SECRET "
            "is missing — /slack/events not mounted."
        )
        return router

    try:
        from slack_bolt import App
        from slack_bolt.adapter.fastapi import SlackRequestHandler
    except ImportError:
        logger.warning(
            "slack-bolt is not installed — /slack/events not mounted. "
            "Install with: pip install nengok[slack]"
        )
        return router

    bolt_app = App(
        token=config.slack_bot_token,
        signing_secret=config.slack_signing_secret,
        raise_error_for_unhandled_request=False,
    )

    def _get_store() -> StateStore:
        return StateStore(config.state_db_path, schema=config.database_schema)

    def _dashboard_url(cluster_id: str) -> str | None:
        if config.slack_dashboard_base_url:
            return f"{config.slack_dashboard_base_url.rstrip('/')}/clusters/{cluster_id}"
        return None

    def _resolve_identity(client, user_id: str) -> str | None:
        try:
            resp = client.users_info(user=user_id)
            user = resp["user"]
            profile = user.get("profile", {})
            name = user.get("real_name") or profile.get("display_name") or user_id
            email = profile.get("email")
            if email:
                return f"Slack: {name} <{email}> ({user_id})"
            return f"Slack: {name} ({user_id})"
        except Exception as exc:
            logger.warning("Failed to resolve Slack identity for %s: %s", user_id, exc)
            return None

    def _update_error(client, channel_id: str, message_ts: str, message: str, cluster_id: str) -> None:
        from nengok.notifiers.slack.messages import build_error_blocks

        try:
            client.chat_update(
                channel=channel_id,
                ts=message_ts,
                blocks=build_error_blocks(message=message, dashboard_url=_dashboard_url(cluster_id)),
                text=message,
            )
        except Exception as exc:
            logger.warning("chat.update error state failed: %s", exc)

    def _update_decision(
        client,
        channel_id: str,
        message_ts: str,
        *,
        cluster_name: str,
        cluster_id: str,
        decision: str,
        reviewer: str,
        reason: str | None,
    ) -> None:
        from nengok.notifiers.slack.messages import build_decision_blocks

        try:
            client.chat_update(
                channel=channel_id,
                ts=message_ts,
                blocks=build_decision_blocks(
                    cluster_name=cluster_name,
                    decision=decision,
                    reviewer=reviewer,
                    reason=reason,
                    dashboard_url=_dashboard_url(cluster_id),
                ),
                text=f"Fix {decision} by {reviewer}",
            )
        except Exception as exc:
            with contextlib.suppress(Exception):
                notification = _get_store().get_notification(
                    notifier_name="slack",
                    event_kind="fix_proposed",
                    subject_id=cluster_id,
                )
                if notification is not None:
                    _get_store().mark_notification_update_failed(
                        notification_id=notification["notification_id"],
                        last_error=str(exc),
                    )
            logger.warning("chat.update decision state failed: %s", exc)

    def _parse_action_value(body: dict, action_id: str) -> tuple[str, str] | None:
        """Extract (cluster_id, event_kind) from the button value. Returns None on parse error."""
        try:
            action = next(a for a in body["actions"] if a["action_id"] == action_id)
            payload = json.loads(action["value"])
            return payload["cluster_id"], payload.get("event_kind", "fix_proposed")
        except Exception:
            logger.warning("Failed to parse action payload for %s", action_id)
            return None

    @bolt_app.action("nengok_approve_fix")
    def handle_approve(ack, body, client):
        ack()

        parsed = _parse_action_value(body, "nengok_approve_fix")
        if not parsed:
            return
        cluster_id, event_kind = parsed
        channel_id = body["container"]["channel_id"]
        message_ts = body["container"]["message_ts"]

        if config.notifier_dry_run:
            _update_error(
                client,
                channel_id,
                message_ts,
                "Notifier dry-run mode — approvals are disabled. Use the dashboard.",
                cluster_id,
            )
            return

        user_id = body["user"]["id"]
        reviewer = _resolve_identity(client, user_id)
        if not reviewer:
            _update_error(
                client,
                channel_id,
                message_ts,
                "Could not resolve your Slack identity. Please approve from the dashboard.",
                cluster_id,
            )
            return

        store = _get_store()
        clusters = store.list_clusters()
        cluster = next((c for c in clusters if c["cluster_id"] == cluster_id), None)
        if not cluster:
            logger.warning("Approve action for unknown cluster %s", cluster_id)
            return

        if cluster["status"] != ClusterStatus.FIX_PROPOSED.value:
            _update_error(
                client,
                channel_id,
                message_ts,
                f"Cluster is no longer pending review (status: {cluster['status']}). Check the dashboard.",
                cluster_id,
            )
            return

        if not store.get_notification(notifier_name="slack", event_kind=event_kind, subject_id=cluster_id):
            logger.warning("No notification row for cluster %s during approve", cluster_id)
            return

        store.record_approval(cluster_id=cluster_id, decision="approved", reviewer=reviewer, reason=None)
        store.mark_status(cluster_id, ClusterStatus.APPROVED)
        _update_decision(
            client,
            channel_id,
            message_ts,
            cluster_name=cluster["name"],
            cluster_id=cluster_id,
            decision="approved",
            reviewer=reviewer,
            reason=None,
        )

    def _open_reason_modal(
        client, body: dict, *, callback_id: str, title: str, cluster_id: str, event_kind: str
    ) -> None:
        channel_id = body["container"]["channel_id"]
        message_ts = body["container"]["message_ts"]
        user_id = body["user"]["id"]
        private_metadata = json.dumps(
            {
                "cluster_id": cluster_id,
                "event_kind": event_kind,
                "channel_id": channel_id,
                "message_ts": message_ts,
                "slack_user_id": user_id,
            }
        )
        client.views_open(
            trigger_id=body["trigger_id"],
            view={
                "type": "modal",
                "callback_id": callback_id,
                "private_metadata": private_metadata,
                "title": {"type": "plain_text", "text": title},
                "submit": {"type": "plain_text", "text": "Submit"},
                "close": {"type": "plain_text", "text": "Cancel"},
                "blocks": [
                    {
                        "type": "input",
                        "block_id": "reason_block",
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "reason_input",
                            "multiline": True,
                        },
                        "label": {"type": "plain_text", "text": "Reason"},
                        "optional": callback_id == "nengok_submit_dismissal_reason",
                    }
                ],
            },
        )

    @bolt_app.action("nengok_reject_fix")
    def handle_reject(ack, body, client):
        ack()
        parsed = _parse_action_value(body, "nengok_reject_fix")
        if not parsed:
            return
        cluster_id, event_kind = parsed
        channel_id = body["container"]["channel_id"]
        message_ts = body["container"]["message_ts"]

        if config.notifier_dry_run:
            _update_error(
                client,
                channel_id,
                message_ts,
                "Notifier dry-run mode — rejections are disabled. Use the dashboard.",
                cluster_id,
            )
            return

        _open_reason_modal(
            client,
            body,
            callback_id="nengok_submit_rejection_reason",
            title="Reject fix",
            cluster_id=cluster_id,
            event_kind=event_kind,
        )

    @bolt_app.action("nengok_dismiss_fix")
    def handle_dismiss(ack, body, client):
        ack()
        parsed = _parse_action_value(body, "nengok_dismiss_fix")
        if not parsed:
            return
        cluster_id, event_kind = parsed
        channel_id = body["container"]["channel_id"]
        message_ts = body["container"]["message_ts"]

        if config.notifier_dry_run:
            _update_error(
                client,
                channel_id,
                message_ts,
                "Notifier dry-run mode — dismissals are disabled. Use the dashboard.",
                cluster_id,
            )
            return

        _open_reason_modal(
            client,
            body,
            callback_id="nengok_submit_dismissal_reason",
            title="Dismiss fix",
            cluster_id=cluster_id,
            event_kind=event_kind,
        )

    def _handle_decision_submission(ack, body, client, *, decision: str) -> None:
        ack()

        metadata = json.loads(body["view"]["private_metadata"])
        cluster_id = metadata["cluster_id"]
        event_kind = metadata.get("event_kind", "fix_proposed")
        channel_id = metadata["channel_id"]
        message_ts = metadata["message_ts"]
        slack_user_id = metadata["slack_user_id"]

        reason_value = (
            body["view"]["state"]["values"].get("reason_block", {}).get("reason_input", {}).get("value")
        )
        reason = reason_value.strip() if reason_value else None

        if config.notifier_dry_run:
            _update_error(
                client,
                channel_id,
                message_ts,
                "Notifier dry-run mode — decisions are disabled. Use the dashboard.",
                cluster_id,
            )
            return

        reviewer = _resolve_identity(client, slack_user_id)
        if not reviewer:
            _update_error(
                client,
                channel_id,
                message_ts,
                "Could not resolve your Slack identity. Please use the dashboard.",
                cluster_id,
            )
            return

        store = _get_store()
        clusters = store.list_clusters()
        cluster = next((c for c in clusters if c["cluster_id"] == cluster_id), None)
        if not cluster or cluster["status"] != ClusterStatus.FIX_PROPOSED.value:
            _update_error(
                client,
                channel_id,
                message_ts,
                "Cluster is no longer pending review. Check the dashboard.",
                cluster_id,
            )
            return

        if not store.get_notification(notifier_name="slack", event_kind=event_kind, subject_id=cluster_id):
            logger.warning("No notification row for cluster %s during %s", cluster_id, decision)
            return

        store.record_approval(cluster_id=cluster_id, decision=decision, reviewer=reviewer, reason=reason)
        store.mark_status(cluster_id, _DECISION_TO_STATUS[decision])
        _update_decision(
            client,
            channel_id,
            message_ts,
            cluster_name=cluster["name"],
            cluster_id=cluster_id,
            decision=decision,
            reviewer=reviewer,
            reason=reason,
        )

    @bolt_app.view("nengok_submit_rejection_reason")
    def handle_rejection_submission(ack, body, client):
        _handle_decision_submission(ack, body, client, decision="rejected")

    @bolt_app.view("nengok_submit_dismissal_reason")
    def handle_dismissal_submission(ack, body, client):
        _handle_decision_submission(ack, body, client, decision="dismissed")

    handler = SlackRequestHandler(bolt_app)

    @router.post("/slack/events")
    async def slack_events(req: Request):
        return await handler.handle(req)

    logger.info("Slack inbound route mounted at /slack/events")
    return router
