import { Badge } from "./ui/Badge";
import type { ClusterStatus } from "../types/cluster";

const TONE: Record<ClusterStatus, Parameters<typeof Badge>[0]["tone"]> = {
  open: "open",
  diagnosed: "diagnosed",
  fix_proposed: "fix",
  approved: "fix",
  rejected: "escalated",
  dismissed: "dismissed",
  escalated: "escalated",
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
  return <Badge tone={TONE[status]}>{LABELS[status]}</Badge>;
}
