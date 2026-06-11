import type { ExperimentCase } from "../types/experiment";

/**
 * Stable display key for an experiment case. Falls back to the row's
 * position when Phoenix returns no case_id, so the outcome strip and
 * the table rows agree on which case is which.
 */
export function caseKey(row: ExperimentCase, index: number): string {
  return row.case_id ?? `#${index + 1}`;
}
