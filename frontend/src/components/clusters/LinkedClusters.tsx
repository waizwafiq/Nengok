import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { fetchClusterLinks } from "../../api/clusters";
import { StatusBadge } from "../StatusBadge";
import { Badge } from "../ui/Badge";
import { Card } from "../ui/Card";

interface Props {
  clusterId: string;
}

/**
 * "Also affects" panel: clusters in other monitored agents that the
 * cross-agent linker confirmed share an upstream cause with this one.
 * Renders nothing when no links exist so single-agent installs never
 * see an empty box.
 */
export function LinkedClusters({ clusterId }: Props) {
  const links = useQuery({
    queryKey: ["clusters", clusterId, "links"],
    queryFn: () => fetchClusterLinks(clusterId),
    enabled: Boolean(clusterId),
    retry: false,
  });

  if (links.isLoading || links.isError || !links.data || links.data.length === 0) {
    return null;
  }

  return (
    <section>
      <h2 className="section-label mb-2">Also affects</h2>
      <Card padding="none">
        <ul className="divide-y divide-border">
          {links.data.map((link) => (
            <li key={link.link_id} className="flex items-start justify-between gap-4 px-4 py-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <Link
                    to={`/clusters/${link.linked_cluster_id}`}
                    className="truncate text-sm font-medium text-foreground hover:text-primary"
                  >
                    {link.linked_name}
                  </Link>
                  <StatusBadge status={link.linked_status} />
                  {link.linked_project ? <Badge tone="primary">{link.linked_project}</Badge> : null}
                </div>
                {link.rationale ? (
                  <p className="mt-1 text-xs text-muted-foreground">{link.rationale}</p>
                ) : null}
              </div>
              <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                {Math.round(link.confidence * 100)}% confidence
              </span>
            </li>
          ))}
        </ul>
      </Card>
    </section>
  );
}
