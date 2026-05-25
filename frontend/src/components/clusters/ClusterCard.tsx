import { Link } from "react-router-dom";
import { StatusBadge } from "../StatusBadge";
import type { Cluster } from "../../types/cluster";

interface Props {
  cluster: Cluster;
}

/**
 * Summary card for a single failure cluster in list views.
 *
 * Shows name, status, member-span count, and last-updated stamp,
 * with a primary action to open the cluster detail page.
 */
export function ClusterCard({ cluster }: Props) {
  const memberCount = parseMemberCount(cluster.member_spans_json);
  return (
    <article className="pane p-4 flex items-start justify-between gap-4">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <Link
            to={`/clusters/${cluster.cluster_id}`}
            className="font-medium text-neutral-900 hover:text-brand-primary truncate"
          >
            {cluster.name}
          </Link>
          <StatusBadge status={cluster.status} />
        </div>
        <p className="text-xs text-neutral-500 mt-1 line-clamp-2">{cluster.description}</p>
        <div className="text-xs text-neutral-500 mt-2 flex gap-3">
          <span>
            {memberCount} member span{memberCount === 1 ? "" : "s"}
          </span>
          <span aria-hidden="true">·</span>
          <span>Updated {formatTimestamp(cluster.updated_at)}</span>
        </div>
      </div>
      <Link
        to={`/clusters/${cluster.cluster_id}`}
        className="shrink-0 self-center text-xs px-3 py-1.5 rounded-md border border-neutral-300 text-neutral-700 hover:bg-neutral-100"
      >
        View
      </Link>
    </article>
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
