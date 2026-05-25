import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { fetchCluster } from "../api/clusters";
import { fetchArtifacts } from "../api/artifacts";
import { submitApproval } from "../api/approvals";
import { PageHeader } from "../components/layout/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { ExperimentTable } from "../components/clusters/ExperimentTable";
import { PromptDiff } from "../components/clusters/PromptDiff";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import type { ApprovalDecision } from "../types/approval";

export function ClusterDetailPage() {
  const { clusterId = "" } = useParams<{ clusterId: string }>();
  const queryClient = useQueryClient();

  const cluster = useQuery({
    queryKey: ["clusters", clusterId],
    queryFn: () => fetchCluster(clusterId),
    enabled: Boolean(clusterId),
  });

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

  if (!cluster.data) {
    return (
      <div className="mx-auto max-w-7xl p-8">
        <p className="section-label">Loading cluster</p>
      </div>
    );
  }

  return (
    <div className="p-8 animate-in fade-in duration-300">
      <PageHeader
        title={cluster.data.name}
        description={cluster.data.description}
        breadcrumb={[
          { label: "Workspace" },
          { label: "Clusters" },
          { label: cluster.data.cluster_id },
        ]}
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
