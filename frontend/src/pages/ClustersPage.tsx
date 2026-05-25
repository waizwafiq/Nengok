import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { fetchClusters } from "../api/clusters";
import { ClusterCard } from "../components/clusters/ClusterCard";
import { PageHeader } from "../components/layout/PageHeader";
import { useLayoutBreadcrumb } from "../components/layout/useLayout";
import { Card } from "../components/ui/Card";
import { Skeleton } from "../components/ui/Skeleton";
import type { ClusterStatus } from "../types/cluster";
import { cn } from "../lib/cn";

const STATUS_FILTERS: { value: ClusterStatus | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "open", label: "Open" },
  { value: "diagnosed", label: "Diagnosed" },
  { value: "fix_proposed", label: "Fix proposed" },
  { value: "approved", label: "Approved" },
  { value: "escalated", label: "Escalated" },
];

export function ClustersPage() {
  useLayoutBreadcrumb([{ label: "Workspace" }, { label: "Clusters" }]);
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
    <div className="p-8 animate-in fade-in duration-300">
      <PageHeader
        title="Clusters"
        description="Each group is a named failure pattern detected by the observer."
        actions={<StatusFilterBar active={activeStatus} onSelect={applyFilter} />}
      />

      {isLoading ? <ClusterListSkeleton /> : null}

      {isError ? (
        <Card padding="lg">
          <p className="text-sm text-destructive">
            Could not load clusters. Is the Nengok server running?
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            Start it with{" "}
            <code className="font-mono text-xs rounded bg-muted px-1.5 py-0.5">
              nengok dashboard
            </code>{" "}
            and reload this page.
          </p>
        </Card>
      ) : null}

      {!isLoading && !isError && clusters.length === 0 ? (
        <EmptyState filtered={activeStatus !== "all"} />
      ) : null}

      <ul className="space-y-3">
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
          className={cn(
            "h-7 px-2.5 text-xs font-medium rounded-md border transition-colors",
            option.value === active
              ? "border-primary bg-primary/10 text-primary"
              : "border-border text-muted-foreground hover:bg-muted hover:text-foreground",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function ClusterListSkeleton() {
  return (
    <ul className="space-y-3">
      {Array.from({ length: 4 }).map((_, index) => (
        <li key={index}>
          <Card>
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0 flex-1 space-y-2">
                <div className="flex items-center gap-2">
                  <Skeleton className="h-4 w-48" />
                  <Skeleton className="h-5 w-16 rounded-full" />
                </div>
                <Skeleton className="h-3 w-3/4" />
                <Skeleton className="h-3 w-1/3" />
              </div>
              <Skeleton className="h-8 w-16" />
            </div>
          </Card>
        </li>
      ))}
    </ul>
  );
}

function EmptyState({ filtered }: { filtered: boolean }) {
  if (filtered) {
    return (
      <div className="rounded-xl border border-dashed border-border bg-card p-6 text-center">
        <p className="text-sm text-muted-foreground">
          No clusters match this filter. Try a different status.
        </p>
      </div>
    );
  }
  return (
    <div className="rounded-xl border border-dashed border-border bg-card p-6 text-center">
      <p className="text-sm text-muted-foreground">
        No clusters yet. Run{" "}
        <code className="font-mono text-xs rounded bg-muted px-1.5 py-0.5">nengok run</code> to
        detect failures.
      </p>
    </div>
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
