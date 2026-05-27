import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { fetchClusterApprovals } from "../../api/approvals";
import type { ApprovalDecision, ApprovalRecord } from "../../types/approval";
import { Badge } from "../ui/Badge";
import { Card } from "../ui/Card";
import { Skeleton } from "../ui/Skeleton";

interface Props {
  clusterId: string;
}

const REASON_COLLAPSE_CHARS = 160;

const DECISION_TONE: Record<ApprovalDecision, Parameters<typeof Badge>[0]["tone"]> = {
  approved: "fix",
  rejected: "escalated",
  dismissed: "dismissed",
  escalated: "escalated",
};

const DECISION_LABEL: Record<ApprovalDecision, string> = {
  approved: "Approved",
  rejected: "Rejected",
  dismissed: "Dismissed",
  escalated: "Escalated",
};

export function ApprovalHistory({ clusterId }: Props) {
  const approvals = useQuery({
    queryKey: ["approvals", clusterId],
    queryFn: () => fetchClusterApprovals(clusterId),
    enabled: Boolean(clusterId),
  });

  if (approvals.isLoading) {
    return <ApprovalHistorySkeleton />;
  }

  if (approvals.isError) {
    return (
      <Card padding="md">
        <p className="text-sm text-destructive">Could not load approval history.</p>
      </Card>
    );
  }

  const rows: ApprovalRecord[] = Array.isArray(approvals.data) ? approvals.data : [];
  if (rows.length === 0) {
    return (
      <Card padding="md" className="border border-dashed border-border bg-card text-center">
        <p className="text-sm text-muted-foreground">
          No approval decisions have been recorded for this cluster yet.
        </p>
      </Card>
    );
  }

  return (
    <Card padding="none">
      <ul className="divide-y divide-border">
        {rows.map((row) => (
          <ApprovalRow key={row.approval_id} row={row} />
        ))}
      </ul>
    </Card>
  );
}

function ApprovalRow({ row }: { row: ApprovalRecord }) {
  const [expanded, setExpanded] = useState(false);
  const reason = row.reason ?? "";
  const isLong = reason.length > REASON_COLLAPSE_CHARS;
  const visibleReason = expanded || !isLong ? reason : `${reason.slice(0, REASON_COLLAPSE_CHARS)}...`;

  return (
    <li className="flex flex-col gap-2 px-4 py-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Badge tone={DECISION_TONE[row.decision]}>{DECISION_LABEL[row.decision]}</Badge>
          <span className="text-foreground font-medium">{row.reviewer ?? "anonymous"}</span>
        </div>
        <time className="text-xs text-muted-foreground tabular-nums" dateTime={row.created_at}>
          {formatTimestamp(row.created_at)}
        </time>
      </div>
      {reason ? (
        <div className="text-xs text-muted-foreground">
          <p className="whitespace-pre-wrap">{visibleReason}</p>
          {isLong ? (
            <button
              type="button"
              onClick={() => setExpanded((prev) => !prev)}
              className="mt-1 text-primary hover:underline"
            >
              {expanded ? "Show less" : "Show more"}
            </button>
          ) : null}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground italic">No reason provided.</p>
      )}
    </li>
  );
}

function ApprovalHistorySkeleton() {
  return (
    <Card padding="md">
      <div className="space-y-3">
        {Array.from({ length: 3 }).map((_, index) => (
          <Skeleton key={index} className="h-10 w-full" />
        ))}
      </div>
    </Card>
  );
}

function formatTimestamp(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return date.toLocaleString();
}
