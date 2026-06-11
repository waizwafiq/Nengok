/**
 * Shared value formatters for the dashboard. Every page renders the
 * same kinds of values (durations, rates, spend, timestamps), so the
 * formatting rules live here instead of being re-implemented per page.
 * Null and NaN render as an em dash so cards stay aligned when a
 * metric has no data yet.
 */

export function formatDuration(seconds: number | null): string {
  if (seconds === null || Number.isNaN(seconds)) {
    return "—";
  }
  if (seconds < 60) {
    return `${seconds.toFixed(0)}s`;
  }
  if (seconds < 3600) {
    return `${(seconds / 60).toFixed(1)}m`;
  }
  if (seconds < 86400) {
    return `${(seconds / 3600).toFixed(1)}h`;
  }
  return `${(seconds / 86400).toFixed(1)}d`;
}

export function formatPercent(value: number | null): string {
  if (value === null || Number.isNaN(value)) {
    return "—";
  }
  return `${(value * 100).toFixed(0)}%`;
}

export function formatDollars(value: number): string {
  return `$${value.toFixed(2)}`;
}

export function formatTokenCount(value: number): string {
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(1)}M`;
  }
  if (value >= 1_000) {
    return `${(value / 1_000).toFixed(1)}k`;
  }
  return value.toString();
}

export function formatDateTime(iso: string): string {
  const parsed = parseIso(iso);
  if (parsed === null) {
    return iso;
  }
  const sameYear = parsed.getFullYear() === new Date().getFullYear();
  return parsed.toLocaleString(undefined, {
    year: sameYear ? undefined : "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function formatDay(iso: string): string {
  const parsed = parseIso(iso);
  if (parsed === null) {
    return iso;
  }
  return parsed.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;

/**
 * Date-only strings ("2026-05-25") are spec'd to parse as UTC
 * midnight, which shifts the rendered day for users west of UTC.
 * The server buckets spend by calendar day, so treat them as local.
 */
function parseIso(iso: string): Date | null {
  const dateOnly = DATE_ONLY.exec(iso);
  const parsed = dateOnly
    ? new Date(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3]))
    : new Date(iso);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}
