import type { CycleStatus } from "../../types/dashboard";

/**
 * Presentation maps for cycle statuses, shared by the overview cards
 * and the cycle cost chart so the same status never renders in two
 * colors.
 */

export const CYCLE_STATUS_ORDER: CycleStatus[] = [
  "ok",
  "skipped_by_triage",
  "over_budget",
  "circuit_broken",
  "failed",
];

export const CYCLE_STATUS_LABEL: Record<CycleStatus, string> = {
  ok: "OK",
  skipped_by_triage: "Skipped by triage",
  over_budget: "Over budget",
  circuit_broken: "Circuit broken",
  failed: "Failed",
};

// failed gets its own darker red because --destructive aliases
// --color-status-escalated; sharing it would make failed and
// circuit-broken cycles indistinguishable in the color-only dot
// strip and bar chart.
export const CYCLE_STATUS_BAR_CLASS: Record<CycleStatus, string> = {
  ok: "bg-status-fix",
  skipped_by_triage: "bg-status-open",
  over_budget: "bg-status-diagnosed",
  circuit_broken: "bg-status-escalated",
  failed: "bg-status-failed",
};

export const CYCLE_STATUS_FILL_CLASS: Record<CycleStatus, string> = {
  ok: "fill-status-fix",
  skipped_by_triage: "fill-status-open",
  over_budget: "fill-status-diagnosed",
  circuit_broken: "fill-status-escalated",
  failed: "fill-status-failed",
};
