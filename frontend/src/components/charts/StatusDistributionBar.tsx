import { cn } from "../../lib/cn";
import type { ClusterStatus } from "../../types/cluster";
import type { ClusterCounts } from "../../types/dashboard";

const SEGMENT_ORDER: ClusterStatus[] = [
  "open",
  "diagnosed",
  "fix_proposed",
  "approved",
  "rejected",
  "escalated",
  "dismissed",
];

const SEGMENT_LABEL: Record<ClusterStatus, string> = {
  open: "Open",
  diagnosed: "Diagnosed",
  fix_proposed: "Fix proposed",
  approved: "Approved",
  rejected: "Rejected",
  escalated: "Escalated",
  dismissed: "Dismissed",
};

const SEGMENT_CLASS: Record<ClusterStatus, string> = {
  open: "bg-status-open",
  diagnosed: "bg-status-diagnosed",
  fix_proposed: "bg-status-fix/50",
  approved: "bg-status-fix",
  rejected: "bg-status-escalated/50",
  escalated: "bg-status-escalated",
  dismissed: "bg-status-dismissed",
};

/**
 * Lifecycle split of every cluster as a segmented bar with a legend.
 * Legend entries keep the label and count in one text node ("Open · 2")
 * so exact-text queries for the stat-tile labels above stay unique.
 * Renders nothing at zero total; the page's empty banner covers that.
 */
export function StatusDistributionBar({ counts }: { counts: ClusterCounts }) {
  const segments = SEGMENT_ORDER.map((status) => ({ status, count: counts[status] })).filter(
    (segment) => segment.count > 0,
  );
  const total = segments.reduce((sum, segment) => sum + segment.count, 0);
  if (total === 0) {
    return null;
  }

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="section-label">Status distribution</span>
        <span className="font-mono text-xs tabular-nums text-muted-foreground">
          {total} cluster{total === 1 ? "" : "s"}
        </span>
      </div>
      <div className="mt-3 flex h-3 w-full overflow-hidden rounded-full bg-muted">
        {segments.map(({ status, count }) => (
          <div
            key={status}
            className={cn(SEGMENT_CLASS[status], "border-r border-card last:border-r-0")}
            style={{ flexGrow: count, flexBasis: 0, minWidth: 6 }}
            title={`${SEGMENT_LABEL[status]}: ${count}`}
          />
        ))}
      </div>
      <div className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1">
        {segments.map(({ status, count }) => (
          <div key={status} className="flex items-center gap-1.5">
            <span className={cn(SEGMENT_CLASS[status], "h-2 w-2 rounded-sm")} aria-hidden="true" />
            <span className="text-xs text-muted-foreground">
              {SEGMENT_LABEL[status]} · {count}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
