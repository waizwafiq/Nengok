import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { fetchCluster } from "../api/clusters";
import { fetchArtifacts } from "../api/artifacts";
import { submitApproval } from "../api/approvals";
import { StatusBadge } from "../components/StatusBadge";
import { ExperimentTable } from "../components/clusters/ExperimentTable";
import { PromptDiff } from "../components/clusters/PromptDiff";
import { Button } from "../components/ui/Button";
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
    return <p className="text-sm text-neutral-500">Loading cluster…</p>;
  }

  return (
    <div className="space-y-6">
      <header className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold">{cluster.data.name}</h1>
          <p className="text-sm text-neutral-500 mt-1">{cluster.data.description}</p>
        </div>
        <StatusBadge status={cluster.data.status} />
      </header>

      <section className="pane p-5 space-y-3">
        <h2 className="text-sm font-medium uppercase tracking-wide text-neutral-500">
          Root-cause analysis
        </h2>
        <pre className="text-xs whitespace-pre-wrap bg-neutral-50 p-3 rounded-md">
          {artifacts.data?.rca ?? "No RCA artifact yet."}
        </pre>
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-medium uppercase tracking-wide text-neutral-500">
          Prompt diff
        </h2>
        <PromptDiff prompt={artifacts.data?.prompt ?? null} />
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-medium uppercase tracking-wide text-neutral-500">
          Experiment results
        </h2>
        <ExperimentTable clusterId={clusterId} />
      </section>

      <section className="flex gap-2">
        <Button onClick={() => decide.mutate("approved")} disabled={decide.isPending}>
          Approve
        </Button>
        <Button
          variant="danger"
          onClick={() => decide.mutate("rejected")}
          disabled={decide.isPending}
        >
          Reject
        </Button>
        <Button
          variant="neutral"
          onClick={() => decide.mutate("dismissed")}
          disabled={decide.isPending}
        >
          Dismiss
        </Button>
      </section>
    </div>
  );
}
