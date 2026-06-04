# Use a notifier dispatcher instead of Slack-direct integration

Status: accepted

Nengok treats Slack as one notifier implementation, not as the notification abstraction. The orchestrator dispatches immutable, pre-redacted notification events to a `NotifierDispatcher`, which walks the ordered enabled notifier list and records delivery in `nengok_notifications` using `UNIQUE(notifier_name, event_kind, subject_id)`. This prevents Slack-shaped config, tables, and dedupe rules from becoming accidental contracts for webhook, email, Teams, or future PR write-back integrations.

## Considered options

- Wire `SlackNotifier` directly from the orchestrator: rejected because the first non-Slack notifier would inherit Slack naming, Slack storage columns, and Slack dedupe assumptions.
- Give every notifier its own table: rejected because common dispatch state and idempotency would fragment across integrations.
- Use a generic dispatcher and generic delivery table: accepted because it mirrors the existing `AgentRunner` plugin discipline and isolates per-channel failures.

## Consequences

- Enabled notifier names come from an ordered `notifiers` list and are resolved through `notifier_registry` dotted-path specs.
- Loaded notifier instances must satisfy the `Notifier` protocol and must have `instance.name == registry_key`; mismatch is a startup error because notifier names participate in deduplication.
- The dispatcher inserts a pending row before calling each notifier, marks success or failure per notifier, logs failures, and never raises notification errors into the orchestrator cycle.
- `notifier_state` is opaque notifier-owned JSON; dispatcher logic must not interpret Slack-specific handles such as `channel_id` or `message_ts`.
