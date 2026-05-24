import type { ClusterStatus } from "../types/cluster";

const STYLES: Record<ClusterStatus, string> = {
  open: "bg-status-open/10 text-status-open border-status-open/30",
  diagnosed: "bg-status-diagnosed/10 text-status-diagnosed border-status-diagnosed/30",
  fix_proposed: "bg-status-fix/10 text-status-fix border-status-fix/30",
  approved: "bg-status-fix/10 text-status-fix border-status-fix/30",
  rejected: "bg-status-escalated/10 text-status-escalated border-status-escalated/30",
  dismissed: "bg-status-dismissed/10 text-status-dismissed border-status-dismissed/30",
  escalated: "bg-status-escalated/10 text-status-escalated border-status-escalated/30",
};

const LABELS: Record<ClusterStatus, string> = {
  open: "Open",
  diagnosed: "Diagnosed",
  fix_proposed: "Fix proposed",
  approved: "Approved",
  rejected: "Rejected",
  dismissed: "Dismissed",
  escalated: "Escalated",
};

export function StatusBadge({ status }: { status: ClusterStatus }) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border ${STYLES[status]}`}
    >
      {LABELS[status]}
    </span>
  );
}
