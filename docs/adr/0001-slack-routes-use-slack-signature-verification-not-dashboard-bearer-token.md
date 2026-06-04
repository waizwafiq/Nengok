# Slack routes use Slack signature verification, not dashboard bearer token

Nengok's dashboard routes are protected by a bearer token (`require_dashboard_token`). Slack cannot send that token in its HTTP callbacks, and the dashboard token cannot verify that a request originated from Slack. Slack routes therefore use Slack request signature verification (via `SLACK_SIGNING_SECRET`) as their sole authentication boundary, and are mounted in `create_app()` without the `api_dependencies` list applied to dashboard routes. The two authentication mechanisms are intentionally separate and non-substitutable: a valid dashboard token does not grant access to Slack routes, and a valid Slack signature does not grant access to dashboard routes.

## Considered options

- Shared bearer token: rejected because Slack cannot be configured to include an arbitrary bearer token in its request headers.
- No authentication on Slack routes: rejected because Slack routes write approval decisions into the state store; unauthenticated access would allow arbitrary approval submissions.
- Slack signature verification only: accepted — Slack signs every outbound request with `SLACK_SIGNING_SECRET`, which is sufficient to verify origin for inbound Slack payloads.

## Consequences

- Tests must explicitly verify the auth boundary separation: a valid Slack signature without a dashboard bearer token must be accepted, and a valid dashboard bearer token without a valid Slack signature must be rejected.
- Slack routes must be mounted at a prefix outside `/api/v1` (e.g. `/slack/events`) because `DashboardRateLimitMiddleware` rate-limits every path under `/api/v1` by per-IP. Slack's interactive payload callbacks originate from Slack's own infrastructure and must not be subject to that cap — a rate-limit response to Slack would cause `trigger_id` expiry and silent interaction failures.
