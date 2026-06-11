import { cn } from "../../lib/cn";
import { caseKey } from "../../lib/experimentHelpers";
import type { ExperimentCase } from "../../types/experiment";

interface CaseOutcomeStripProps {
  cases: ExperimentCase[];
  hoveredCaseId: string | null;
  onHover: (caseId: string | null) => void;
}

/**
 * One square per experiment case so the failure pattern is visible
 * without scrolling the table. Hover is shared with the table rows
 * through hoveredCaseId, so pointing at a square highlights its row
 * and vice versa.
 */
export function CaseOutcomeStrip({ cases, hoveredCaseId, onHover }: CaseOutcomeStripProps) {
  if (cases.length === 0) {
    return null;
  }
  const scored = cases.filter((row) => row.passed !== undefined);
  const passedCount = scored.filter((row) => row.passed).length;

  return (
    <div className="flex items-center justify-between gap-3">
      <div className="flex flex-wrap gap-1">
        {cases.map((row, index) => {
          const key = caseKey(row, index);
          const outcome =
            row.passed === undefined ? "not scored" : row.passed ? "passed" : "failed";
          return (
            <button
              key={key}
              type="button"
              aria-label={`${key} ${outcome}`}
              title={`${key} · ${outcome}`}
              onMouseEnter={() => onHover(key)}
              onMouseLeave={() => onHover(null)}
              onFocus={() => onHover(key)}
              onBlur={() => onHover(null)}
              className={cn(
                "h-3 w-3 rounded-[3px] transition-transform",
                row.passed === undefined
                  ? "bg-muted"
                  : row.passed
                    ? "bg-status-fix"
                    : "bg-status-escalated",
                hoveredCaseId === key && "scale-125 ring-1 ring-ring",
              )}
            />
          );
        })}
      </div>
      {scored.length > 0 ? (
        <span className="shrink-0 font-mono text-xs tabular-nums text-muted-foreground">
          {passedCount} of {scored.length} passed
        </span>
      ) : null}
    </div>
  );
}
