import { Link } from "react-router-dom";
import { ChevronRight } from "lucide-react";
import { StatusBadge } from "../StatusBadge";
import { Badge } from "../ui/Badge";
import { Card } from "../ui/Card";
import type { Cluster } from "../../types/cluster";

interface Props {
  cluster: Cluster;
}

export function ClusterCard({ cluster }: Props) {
  const memberCount = parseMemberCount(cluster.member_spans_json);
  return (
    <Card className="transition-colors hover:ring-primary/40">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Link
              to={`/clusters/${cluster.cluster_id}`}
              className="truncate text-sm font-medium text-foreground hover:text-primary"
            >
              {cluster.name}
            </Link>
            <StatusBadge status={cluster.status} />
            {cluster.project ? <Badge tone="primary">{cluster.project}</Badge> : null}
          </div>
          <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{cluster.description}</p>
          <div className="mt-2 flex items-center gap-3 text-xs text-muted-foreground">
            <span className="entity-id">
              {memberCount} member span{memberCount === 1 ? "" : "s"}
            </span>
            <span aria-hidden="true" className="text-muted-foreground/40">·</span>
            <span>Updated {formatTimestamp(cluster.updated_at)}</span>
          </div>
        </div>
        <Link
          to={`/clusters/${cluster.cluster_id}`}
          className="flex h-8 shrink-0 items-center gap-1 self-center rounded-md border border-border px-2.5 text-xs font-medium text-foreground transition-colors hover:bg-muted"
        >
          View
          <ChevronRight className="h-3.5 w-3.5" />
        </Link>
      </div>
    </Card>
  );
}

function parseMemberCount(json: string): number {
  try {
    const parsed = JSON.parse(json);
    return Array.isArray(parsed) ? parsed.length : 0;
  } catch {
    return 0;
  }
}

function formatTimestamp(iso: string): string {
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) {
    return iso;
  }
  return dt.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
