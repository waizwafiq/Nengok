import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { fetchCluster } from "../api/clusters";
import { fetchArtifacts } from "../api/artifacts";
import { submitApproval } from "../api/approvals";
import { StatusBadge } from "../components/StatusBadge";
import { ExperimentTable } from "../components/clusters/ExperimentTable";
import { PromptDiff } from "../components/clusters/PromptDiff";
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
        <button
          onClick={() => decide.mutate("approved")}
          className="px-4 py-2 rounded-md bg-status-fix text-white text-sm hover:opacity-90"
          disabled={decide.isPending}
        >
          Approve
        </button>
        <button
          onClick={() => decide.mutate("rejected")}
          className="px-4 py-2 rounded-md bg-status-escalated text-white text-sm hover:opacity-90"
          disabled={decide.isPending}
        >
          Reject
        </button>
        <button
          onClick={() => decide.mutate("dismissed")}
          className="px-4 py-2 rounded-md border border-neutral-300 text-neutral-700 text-sm hover:bg-neutral-100"
          disabled={decide.isPending}
        >
          Dismiss
        </button>
      </section>
    </div>
  );
}
