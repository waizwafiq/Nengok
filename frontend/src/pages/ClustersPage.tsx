import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { fetchClusters } from "../api/clusters";
import { ClusterCard } from "../components/clusters/ClusterCard";
import type { ClusterStatus } from "../types/cluster";

const STATUS_FILTERS: { value: ClusterStatus | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "open", label: "Open" },
  { value: "diagnosed", label: "Diagnosed" },
  { value: "fix_proposed", label: "Fix proposed" },
  { value: "approved", label: "Approved" },
  { value: "escalated", label: "Escalated" },
];

export function ClustersPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const statusParam = searchParams.get("status");
  const activeStatus = isClusterStatus(statusParam) ? statusParam : "all";

  const { data: clusters = [], isLoading, isError } = useQuery({
    queryKey: ["clusters", activeStatus],
    queryFn: () => fetchClusters(activeStatus === "all" ? undefined : activeStatus),
  });

  function applyFilter(value: ClusterStatus | "all") {
    const next = new URLSearchParams(searchParams);
    if (value === "all") {
      next.delete("status");
    } else {
      next.set("status", value);
    }
    setSearchParams(next, { replace: true });
  }

  return (
    <div className="space-y-4">
      <header className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Clusters</h1>
        <StatusFilterBar active={activeStatus} onSelect={applyFilter} />
      </header>

      {isLoading ? <p className="text-sm text-neutral-500">Loading clusters…</p> : null}

      {isError ? (
        <p className="text-sm text-status-escalated">
          Could not load clusters. Is the Nengok server running?
        </p>
      ) : null}

      {!isLoading && !isError && clusters.length === 0 ? (
        <EmptyState filtered={activeStatus !== "all"} />
      ) : null}

      <ul className="space-y-2">
        {clusters.map((cluster) => (
          <li key={cluster.cluster_id}>
            <ClusterCard cluster={cluster} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function StatusFilterBar({
  active,
  onSelect,
}: {
  active: ClusterStatus | "all";
  onSelect: (value: ClusterStatus | "all") => void;
}) {
  return (
    <div className="flex flex-wrap gap-1">
      {STATUS_FILTERS.map((option) => (
        <button
          key={option.value}
          onClick={() => onSelect(option.value)}
          className={[
            "px-2.5 py-1 text-xs rounded-md border transition-colors",
            option.value === active
              ? "border-brand-primary bg-brand-primary/10 text-brand-primary"
              : "border-neutral-200 text-neutral-600 hover:bg-neutral-100",
          ].join(" ")}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function EmptyState({ filtered }: { filtered: boolean }) {
  if (filtered) {
    return (
      <p className="text-sm text-neutral-500">
        No clusters match this filter. Try a different status.
      </p>
    );
  }
  return (
    <p className="text-sm text-neutral-500">
      No clusters yet. Run <code className="font-mono">nengok run</code> to detect failures.
    </p>
  );
}

function isClusterStatus(value: string | null): value is ClusterStatus {
  return (
    value === "open" ||
    value === "diagnosed" ||
    value === "fix_proposed" ||
    value === "approved" ||
    value === "rejected" ||
    value === "dismissed" ||
    value === "escalated"
  );
}
