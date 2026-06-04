"""Slack notifier — first built-in implementation of the Notifier protocol.

Sends fix-proposed notifications as Block Kit messages via chat.postMessage.
Returns NotifierResult with notifier_state={"channel_id": ..., "message_ts": ...}
on success so the dispatcher can persist the Slack handle for later chat.update.
"""

from __future__ import annotations

from nengok.errors import OptionalDependencyError
from nengok.notifiers.events import EscalationEvent, FixProposedEvent
from nengok.notifiers.protocol import NotifierResult
from nengok.utils.logging import get_logger

logger = get_logger(__name__)


class SlackNotifier:
    """Notifier implementation for Slack via slack-sdk WebClient."""

    def __init__(
        self,
        *,
        bot_token: str | None,
        signing_secret: str | None,
        default_channel_id: str | None,
        dashboard_base_url: str | None = None,
        max_summary_chars: int = 600,
    ) -> None:
        if not bot_token:
            raise ValueError("SlackNotifier requires bot_token")
        if not default_channel_id:
            raise ValueError("SlackNotifier requires default_channel_id")
        try:
            from slack_sdk import WebClient
        except ImportError as exc:
            raise OptionalDependencyError(
                "slack-sdk is required for the Slack notifier but is not installed.",
                install_hint="pip install nengok[slack]",
            ) from exc

        self._client = WebClient(token=bot_token)
        self._channel_id = default_channel_id
        self._dashboard_base_url = dashboard_base_url
        self._max_summary_chars = max_summary_chars

    @property
    def name(self) -> str:
        return "slack"

    def notify_fix_proposed(self, event: FixProposedEvent, *, dry_run: bool) -> NotifierResult:
        from nengok.notifiers.slack.messages import build_fix_proposed_blocks

        try:
            blocks = build_fix_proposed_blocks(
                event,
                dry_run=dry_run,
                dashboard_base_url=self._dashboard_base_url,
            )
            response = self._client.chat_postMessage(
                channel=self._channel_id,
                blocks=blocks,
                text=f"Nengok fix ready for review: {event.cluster_name}",
            )
            return NotifierResult(
                success=True,
                notifier_state={
                    "channel_id": self._channel_id,
                    "message_ts": response["ts"],
                },
            )
        except Exception as exc:
            logger.warning("SlackNotifier.notify_fix_proposed failed: %s", exc)
            return NotifierResult(success=False, error=str(exc))

    def notify_escalation(self, event: EscalationEvent, *, dry_run: bool) -> NotifierResult:
        return NotifierResult(success=True)
