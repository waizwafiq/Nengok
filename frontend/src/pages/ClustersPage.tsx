import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { fetchClusters } from "../api/clusters";
import { StatusBadge } from "../components/StatusBadge";

export function ClustersPage() {
  const { data: clusters = [], isLoading } = useQuery({
    queryKey: ["clusters"],
    queryFn: () => fetchClusters(),
  });

  if (isLoading) {
    return <p className="text-sm text-neutral-500">Loading clusters…</p>;
  }

  if (clusters.length === 0) {
    return (
      <div className="space-y-3">
        <h1 className="text-2xl font-semibold">Clusters</h1>
        <p className="text-sm text-neutral-500">
          No clusters yet. Run <code className="font-mono">nengok run</code> to detect failures.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Clusters</h1>
      <ul className="space-y-2">
        {clusters.map((cluster) => (
          <li key={cluster.cluster_id} className="pane p-4 flex items-center justify-between">
            <div>
              <Link
                to={`/clusters/${cluster.cluster_id}`}
                className="font-medium text-neutral-900 hover:text-brand-primary"
              >
                {cluster.name}
              </Link>
              <p className="text-xs text-neutral-500 mt-1">{cluster.description}</p>
            </div>
            <StatusBadge status={cluster.status} />
          </li>
        ))}
      </ul>
    </div>
  );
}
