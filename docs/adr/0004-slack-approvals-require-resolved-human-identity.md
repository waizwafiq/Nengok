# Slack approvals require resolved human identity

Status: accepted

Slack approval actions must resolve the Slack user to a real human identity before calling `record_approval()`. The reviewer string recorded in the audit log is `Slack: Real Name <email> (user_id)`, resolved via Slack profile APIs using MVP-required `users:read` and `users:read.email` scopes. If identity resolution fails, Nengok does not record a degraded or anonymous approval; it updates the Slack message with an error state and dashboard link so the reviewer can use the canonical dashboard path.

## Considered options

- Record Slack display name or user id only: rejected because a two-year audit bundle should not require a later Slack API lookup to identify the approver.
- Fall back to `Slack: unresolved <user_id>` on lookup failure: rejected because that preserves traceability for operators but loses the self-contained human identity required by the audit story.
- Require resolved identity before persistence: accepted because Slack is a convenience review surface and the dashboard remains available when Slack cannot identify a user.

## Consequences

- Slack action handlers must call `ack()` before identity resolution; no Slack profile lookup, Phoenix call, or Gemini call belongs before `ack()`.
- Approve can resolve identity after `ack()` and then update the original message; Reject and Dismiss open their modal first and resolve identity during `view_submission`.
- Scope failures are configuration errors surfaced in Slack and logs, not silently degraded approvals.
