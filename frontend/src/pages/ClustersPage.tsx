import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { fetchClusters } from "../api/clusters";
import { ClusterCard } from "../components/clusters/ClusterCard";
import { PageHeader } from "../components/layout/PageHeader";
import { useLayoutBreadcrumb } from "../components/layout/useLayout";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorState, RestartServerHint } from "../components/ui/ErrorState";
import { InlineCode } from "../components/ui/InlineCode";
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
  const activeProject = searchParams.get("project") ?? "all";

  const statusArg = activeStatus === "all" ? undefined : activeStatus;
  const { data: clusters = [], isLoading, isError } = useQuery({
    queryKey: ["clusters", activeStatus, activeProject],
    queryFn: () =>
      activeProject === "all" ? fetchClusters(statusArg) : fetchClusters(statusArg, activeProject),
  });

  const { data: allClusters = [] } = useQuery({
    queryKey: ["clusters"],
    queryFn: () => fetchClusters(),
  });
  const projects = distinctProjects(allClusters);

  function applyFilter(value: ClusterStatus | "all") {
    const next = new URLSearchParams(searchParams);
    if (value === "all") {
      next.delete("status");
    } else {
      next.set("status", value);
    }
    setSearchParams(next, { replace: true });
  }

  function applyProjectFilter(value: string) {
    const next = new URLSearchParams(searchParams);
    if (value === "all") {
      next.delete("project");
    } else {
      next.set("project", value);
    }
    setSearchParams(next, { replace: true });
  }

  return (
    <div className="p-8 animate-in fade-in duration-300">
      <PageHeader
        title="Clusters"
        description="Each group is a named failure pattern detected by the observer."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {projects.length > 1 ? (
              <ProjectFilter
                projects={projects}
                active={activeProject}
                onSelect={applyProjectFilter}
              />
            ) : null}
            <StatusFilterBar active={activeStatus} onSelect={applyFilter} />
          </div>
        }
      />

      {isLoading ? <ClusterListSkeleton /> : null}

      {isError ? (
        <ErrorState
          title="Could not load clusters. Is the Nengok server running?"
          hint={<RestartServerHint />}
        />
      ) : null}

      {!isLoading && !isError && clusters.length === 0 ? (
        activeStatus !== "all" ? (
          <EmptyState>No clusters match this filter. Try a different status.</EmptyState>
        ) : (
          <EmptyState>
            No clusters yet. Run <InlineCode>nengok run</InlineCode> to detect failures.
          </EmptyState>
        )
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

/**
 * Project dropdown for installs that monitor more than one Phoenix
 * project. Hidden entirely in single-project mode so the existing
 * layout stays untouched.
 */
function ProjectFilter({
  projects,
  active,
  onSelect,
}: {
  projects: string[];
  active: string;
  onSelect: (value: string) => void;
}) {
  return (
    <select
      aria-label="Filter by project"
      value={active}
      onChange={(event) => onSelect(event.target.value)}
      className="h-7 rounded-md border border-border bg-background px-2 text-xs font-medium text-muted-foreground hover:text-foreground focus:outline-none focus:ring-2 focus:ring-ring/40"
    >
      <option value="all">All projects</option>
      {projects.map((project) => (
        <option key={project} value={project}>
          {project}
        </option>
      ))}
    </select>
  );
}

function distinctProjects(clusters: { project?: string | null }[]): string[] {
  const seen = new Set<string>();
  for (const cluster of clusters) {
    if (cluster.project) {
      seen.add(cluster.project);
    }
  }
  return [...seen].sort();
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
