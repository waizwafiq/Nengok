import { formatPercent } from "../../lib/format";
import type { ExperimentSummary } from "../../types/experiment";
import { Badge } from "../ui/Badge";
import { Card } from "../ui/Card";

/**
 * Baseline-vs-fix pass rates as paired bars with a delta badge per
 * group, so a reviewer sees the gain (or regression) without doing
 * the subtraction. Golden-set losses get an explicit warning since
 * they are the overfitting signal.
 */
export function PassRateComparison({ summary }: { summary: ExperimentSummary }) {
  const goldenRegressed = summary.golden_fix_pass_rate < summary.golden_baseline_pass_rate;
  return (
    <Card>
      <div className="space-y-4">
        <RateGroup
          label="Cluster cases"
          baseline={summary.baseline_pass_rate}
          fix={summary.fix_pass_rate}
        />
        <RateGroup
          label="Golden set"
          baseline={summary.golden_baseline_pass_rate}
          fix={summary.golden_fix_pass_rate}
        />
        {goldenRegressed ? (
          <p className="text-xs text-status-escalated">
            The fix loses ground on the golden set. Check for overfitting before approving.
          </p>
        ) : null}
      </div>
    </Card>
  );
}

function RateGroup({ label, baseline, fix }: { label: string; baseline: number; fix: number }) {
  const deltaPts = Math.round((fix - baseline) * 100);
  return (
    <div>
      <div className="flex items-center justify-between gap-3">
        <span className="section-label">{label}</span>
        <Badge tone={deltaPts > 0 ? "fix" : deltaPts < 0 ? "escalated" : "neutral"}>
          {deltaPts > 0 ? `+${deltaPts} pts` : deltaPts < 0 ? `${deltaPts} pts` : "±0 pts"}
        </Badge>
      </div>
      <div className="mt-2 space-y-1.5">
        <RateTrack label="base" value={baseline} fillClassName="bg-neutral-500" />
        <RateTrack label="fix" value={fix} fillClassName="bg-status-fix" />
      </div>
    </div>
  );
}

function RateTrack({
  label,
  value,
  fillClassName,
}: {
  label: string;
  value: number;
  fillClassName: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-8 shrink-0 text-[10px] text-muted-foreground">{label}</span>
      <div className="h-2.5 w-full overflow-hidden rounded-full bg-muted">
        <div
          className={`h-full rounded-full ${fillClassName}`}
          style={{ width: `${Math.round(value * 100)}%` }}
          aria-hidden="true"
        />
      </div>
      <span className="w-10 shrink-0 text-right font-mono text-xs tabular-nums text-foreground">
        {formatPercent(value)}
      </span>
    </div>
  );
}
