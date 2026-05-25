import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { fetchCluster } from "../api/clusters";
import { fetchArtifacts } from "../api/artifacts";
import { submitApproval } from "../api/approvals";
import { PageHeader } from "../components/layout/PageHeader";
import { useLayoutBreadcrumb } from "../components/layout/useLayout";
import { StatusBadge } from "../components/StatusBadge";
import { ExperimentTable } from "../components/clusters/ExperimentTable";
import { PromptDiff } from "../components/clusters/PromptDiff";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Skeleton } from "../components/ui/Skeleton";
import type { ApprovalDecision } from "../types/approval";

export function ClusterDetailPage() {
  const { clusterId = "" } = useParams<{ clusterId: string }>();
  const queryClient = useQueryClient();

  const cluster = useQuery({
    queryKey: ["clusters", clusterId],
    queryFn: () => fetchCluster(clusterId),
    enabled: Boolean(clusterId),
  });

  useLayoutBreadcrumb([
    { label: "Workspace" },
    { label: "Clusters", href: "/clusters" },
    { label: cluster.data?.name ?? clusterId },
  ]);

  const artifacts = useQuery({
    queryKey: ["artifacts", clusterId],
    queryFn: () => fetchArtifacts(clusterId),
    enabled: Boolean(clusterId),
    retry: false,
  });

  const decide = useMutation({
    mutationFn: (decision: ApprovalDecision) => submitApproval(clusterId, decision),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["clusters"] });
    },
  });

  if (cluster.isLoading) {
    return <ClusterDetailSkeleton />;
  }

  if (cluster.isError || !cluster.data) {
    return (
      <div className="p-8 animate-in fade-in duration-300">
        <PageHeader
          title="Cluster"
          actions={
            <Link
              to="/clusters"
              className="entity-id rounded-md border border-border px-2 py-1 hover:bg-muted"
            >
              Back
            </Link>
          }
        />
        <Card padding="lg">
          <p className="text-sm text-destructive">
            Could not load this cluster. It may have been removed, or the Nengok server is offline.
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            Return to the{" "}
            <Link to="/clusters" className="text-primary hover:underline">
              clusters list
            </Link>{" "}
            or restart the server with{" "}
            <code className="font-mono text-xs rounded bg-muted px-1.5 py-0.5">
              nengok dashboard
            </code>
            .
          </p>
        </Card>
      </div>
    );
  }

  return (
    <div className="p-8 animate-in fade-in duration-300">
      <PageHeader
        title={cluster.data.name}
        description={cluster.data.description}
        actions={
          <div className="flex items-center gap-2">
            <StatusBadge status={cluster.data.status} />
            <Link
              to="/clusters"
              className="entity-id rounded-md border border-border px-2 py-1 hover:bg-muted"
            >
              Back
            </Link>
          </div>
        }
      />

      <section className="space-y-6">
        <Card padding="lg">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="section-label">Root-cause analysis</h2>
          </div>
          <pre className="rounded-md bg-muted/50 p-3 text-xs whitespace-pre-wrap text-foreground">
            {artifacts.data?.rca ?? "No RCA artifact yet."}
          </pre>
        </Card>

        <div className="space-y-3">
          <h2 className="section-label">Prompt diff</h2>
          <PromptDiff prompt={artifacts.data?.prompt ?? null} />
        </div>

        <div className="space-y-3">
          <h2 className="section-label">Experiment results</h2>
          <ExperimentTable clusterId={clusterId} />
        </div>

        <Card>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="section-label">Approval</h2>
              <p className="mt-1 text-xs text-muted-foreground">
                Approve ships the fix to the artifacts directory. Reject flags it for review.
              </p>
            </div>
            <div className="flex gap-2">
              <Button onClick={() => decide.mutate("approved")} disabled={decide.isPending}>
                Approve
              </Button>
              <Button
                variant="destructive"
                onClick={() => decide.mutate("rejected")}
                disabled={decide.isPending}
              >
                Reject
              </Button>
              <Button
                variant="outline"
                onClick={() => decide.mutate("dismissed")}
                disabled={decide.isPending}
              >
                Dismiss
              </Button>
            </div>
          </div>
        </Card>
      </section>
    </div>
  );
}

function ClusterDetailSkeleton() {
  return (
    <div className="p-8 animate-in fade-in duration-300">
      <div className="mb-7 flex items-start justify-between gap-4">
        <div className="min-w-0 space-y-2">
          <Skeleton className="h-6 w-64" />
          <Skeleton className="h-4 w-96" />
        </div>
        <Skeleton className="h-8 w-24" />
      </div>
      <section className="space-y-6">
        <Card padding="lg">
          <Skeleton className="mb-3 h-3 w-32" />
          <div className="space-y-2">
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-11/12" />
            <Skeleton className="h-3 w-4/5" />
          </div>
        </Card>
        <div className="space-y-3">
          <Skeleton className="h-3 w-24" />
          <Card padding="md">
            <Skeleton className="h-24 w-full" />
          </Card>
        </div>
        <div className="space-y-3">
          <Skeleton className="h-3 w-32" />
          <Card padding="md">
            <Skeleton className="h-32 w-full" />
          </Card>
        </div>
      </section>
    </div>
  );
}
