import { Link } from "react-router-dom";
import { ChevronRight } from "lucide-react";
import { parseMemberSpans } from "../../lib/clusterHelpers";
import { formatDateTime } from "../../lib/format";
import { StatusBadge } from "../StatusBadge";
import { Badge } from "../ui/Badge";
import { Card } from "../ui/Card";
import { LinkButton } from "../ui/LinkButton";
import type { Cluster } from "../../types/cluster";

interface Props {
  cluster: Cluster;
}

export function ClusterCard({ cluster }: Props) {
  const memberCount = parseMemberSpans(cluster.member_spans_json).length;
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
            <span className="tabular-nums">
              {memberCount} member span{memberCount === 1 ? "" : "s"}
            </span>
            <span aria-hidden="true" className="text-muted-foreground/40">
              ·
            </span>
            <span>Updated {formatDateTime(cluster.updated_at)}</span>
          </div>
        </div>
        <LinkButton to={`/clusters/${cluster.cluster_id}`} className="self-center">
          View
          <ChevronRight className="h-3.5 w-3.5" />
        </LinkButton>
      </div>
    </Card>
  );
}
