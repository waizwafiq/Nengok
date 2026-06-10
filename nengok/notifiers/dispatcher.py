"""Dispatcher: walks enabled notifiers, isolates per-channel failures.

The orchestrator calls dispatcher.dispatch(event) and never touches a
notifier directly. Failures in one notifier do not block others. Notification
errors never propagate into the orchestrator cycle.

Deduplication is DB-level: inserting a pending row for an already-existing
(notifier_name, event_kind, subject_id) triple fails silently and skips that
notifier.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nengok.notifiers.events import EscalationEvent, FixProposedEvent
from nengok.notifiers.loader import load_notifier
from nengok.notifiers.protocol import Notifier
from nengok.utils.logging import get_logger

if TYPE_CHECKING:
    from nengok.config import NengokConfig
    from nengok.state.store import StateStore

logger = get_logger(__name__)

_DEFAULT_REGISTRY: dict[str, str] = {
    "slack": "nengok.notifiers.slack.notifier:SlackNotifier",
}


class NotifierDispatcher:
    def __init__(
        self,
        notifiers: list[Notifier],
        store: StateStore,
        *,
        dry_run: bool = False,
    ) -> None:
        self._notifiers = notifiers
        self._store = store
        self._dry_run = dry_run

    @classmethod
    def from_config(cls, *, config: NengokConfig, store: StateStore) -> NotifierDispatcher:
        """Build a dispatcher from NengokConfig, loading and validating all notifiers."""
        from nengok.errors import NotifierLoadError

        if not config.notifiers:
            return cls(notifiers=[], store=store, dry_run=config.notifier_dry_run)

        registry = {**_DEFAULT_REGISTRY, **config.notifier_registry}
        notifiers: list[Notifier] = []

        for name in config.notifiers:
            spec = registry.get(name)
            if not spec:
                raise NotifierLoadError(
                    f"Notifier '{name}' is listed in `notifiers` but has no entry in "
                    "`notifier_registry`. Add it or remove it from the enabled list.",
                    notifier_name=name,
                )
            kwargs = _build_kwargs(name, config)
            notifier = load_notifier(spec, kwargs, registry_key=name)
            notifiers.append(notifier)
            logger.info("Loaded notifier '%s' from %s", name, spec)

        return cls(notifiers=notifiers, store=store, dry_run=config.notifier_dry_run)

    def dispatch(self, event: FixProposedEvent | EscalationEvent) -> None:
        """Dispatch event to all enabled notifiers, isolating per-channel failures."""
        for notifier in self._notifiers:
            notification_id = self._store.insert_notification_pending(
                notifier_name=notifier.name,
                event_kind=event.event_kind,
                subject_id=event.cluster_id,
            )
            if notification_id is None:
                logger.debug(
                    "Notifier '%s' already has a row for (%s, %s) — skipping",
                    notifier.name,
                    event.event_kind,
                    event.cluster_id,
                )
                continue

            try:
                if isinstance(event, FixProposedEvent):
                    result = notifier.notify_fix_proposed(event, dry_run=self._dry_run)
                else:
                    result = notifier.notify_escalation(event, dry_run=self._dry_run)

                if result.success:
                    self._store.mark_notification_sent(
                        notification_id=notification_id,
                        notifier_state=result.notifier_state,
                    )
                else:
                    self._store.mark_notification_failed(
                        notification_id=notification_id,
                        last_error=result.error or "unknown",
                    )
                    logger.warning(
                        "Notifier '%s' returned failure for %s/%s: %s",
                        notifier.name,
                        event.event_kind,
                        event.cluster_id,
                        result.error,
                    )
            except Exception as exc:
                logger.warning(
                    "Notifier '%s' raised for %s/%s: %s",
                    notifier.name,
                    event.event_kind,
                    event.cluster_id,
                    exc,
                )
                self._store.mark_notification_failed(
                    notification_id=notification_id,
                    last_error=str(exc),
                )


def _build_kwargs(name: str, config: Any) -> dict[str, Any]:
    """Assemble constructor kwargs for a notifier from NengokConfig."""
    if name == "slack":
        return {
            "bot_token": config.slack_bot_token,
            "signing_secret": config.slack_signing_secret,
            "default_channel_id": config.slack_default_channel_id,
            "dashboard_base_url": config.slack_dashboard_base_url,
            "max_summary_chars": config.slack_max_summary_chars,
        }
    return dict(getattr(config, "notifier_configs", {}).get(name, {}))
