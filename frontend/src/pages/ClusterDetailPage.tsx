import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ArrowLeft } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { fetchCluster } from "../api/clusters";
import { fetchArtifacts } from "../api/artifacts";
import { apiClient } from "../api/client";
import { submitApproval } from "../api/approvals";
import { fetchLatestExperiment } from "../api/experiments";
import { ApprovalHistory } from "../components/clusters/ApprovalHistory";
import { LinkedClusters } from "../components/clusters/LinkedClusters";
import { PageHeader } from "../components/layout/PageHeader";
import { SectionHeader } from "../components/layout/SectionHeader";
import { useLayoutBreadcrumb } from "../components/layout/useLayout";
import { StatusBadge } from "../components/StatusBadge";
import { ExperimentTable } from "../components/clusters/ExperimentTable";
import { PromptDiff } from "../components/clusters/PromptDiff";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorState } from "../components/ui/ErrorState";
import { InlineCode } from "../components/ui/InlineCode";
import { LinkButton } from "../components/ui/LinkButton";
import { Skeleton } from "../components/ui/Skeleton";
import { WrongMergePanel } from "../components/clusters/WrongMergePanel";
import { parseMemberSpans } from "../lib/clusterHelpers";
import { formatDateTime, formatPercent } from "../lib/format";
import type { ApprovalDecision, FeedbackTag } from "../types/approval";
import type { Cluster, RootCauseHypothesis } from "../types/cluster";
import type { ExperimentSummary } from "../types/experiment";

const FEEDBACK_TAG_OPTIONS: { value: FeedbackTag | ""; label: string }[] = [
  { value: "", label: "No clustering feedback" },
  { value: "duplicate_cluster", label: "Duplicate cluster" },
  { value: "mixed_root_causes", label: "Mixed root causes" },
  { value: "not_a_failure", label: "Not a failure" },
];

interface ReviewerIdentity {
  reviewer: string;
  source: "request" | "env" | "file" | "fallback";
}

async function fetchReviewerIdentity(): Promise<ReviewerIdentity> {
  const response = await apiClient.get<ReviewerIdentity>("/reviewer");
  return response.data;
}

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

  // Same query key as ExperimentTable, so react-query dedupes the
  // request; this read only feeds the evidence line in the approval card.
  const experiment = useQuery({
    queryKey: ["experiments", clusterId, "latest"],
    queryFn: () => fetchLatestExperiment(clusterId),
    enabled: Boolean(clusterId),
    retry: false,
  });

  const reviewer = useQuery({
    queryKey: ["reviewer"],
    queryFn: fetchReviewerIdentity,
  });

  const [reason, setReason] = useState("");
  const [feedbackTag, setFeedbackTag] = useState<FeedbackTag | "">("");

  const decide = useMutation({
    mutationFn: (decision: ApprovalDecision) =>
      submitApproval(clusterId, {
        decision,
        reviewer: reviewer.data?.source === "fallback" ? null : reviewer.data?.reviewer ?? null,
        reason: reason.trim() || null,
        feedback_tag: feedbackTag || null,
      }),
    onSuccess: () => {
      setReason("");
      setFeedbackTag("");
      queryClient.invalidateQueries({ queryKey: ["clusters"] });
      queryClient.invalidateQueries({ queryKey: ["approvals", clusterId] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });

  const reviewerIsAnonymous = reviewer.data?.source === "fallback";

  if (cluster.isLoading) {
    return <ClusterDetailSkeleton />;
  }

  if (cluster.isError || !cluster.data) {
    return (
      <div className="p-8 animate-in fade-in duration-300">
        <PageHeader
          title="Cluster"
          actions={
            <LinkButton to="/clusters">
              <ArrowLeft className="h-3.5 w-3.5" />
              Back to clusters
            </LinkButton>
          }
        />
        <ErrorState
          title="Could not load this cluster. It may have been removed, or the Nengok server is offline."
          hint={
            <>
              Return to the{" "}
              <Link to="/clusters" className="text-primary hover:underline">
                clusters list
              </Link>{" "}
              or restart the server with <InlineCode>nengok dashboard</InlineCode>.
            </>
          }
        />
      </div>
    );
  }

  const hypothesis = parseHypothesis(cluster.data.hypothesis_json);

  return (
    <div className="p-8 animate-in fade-in duration-300">
      <PageHeader
        title={cluster.data.name}
        description={cluster.data.description}
        actions={
          <div className="flex items-center gap-2">
            <StatusBadge status={cluster.data.status} />
            <LinkButton to="/clusters">
              <ArrowLeft className="h-3.5 w-3.5" />
              Back to clusters
            </LinkButton>
          </div>
        }
      />

      <ClusterMetaRow cluster={cluster.data} />

      <div className="space-y-8">
        {hypothesis ? <HypothesisCard hypothesis={hypothesis} /> : null}

        <section>
          <SectionHeader title="Root-cause analysis" />
          {artifacts.data?.rca ? (
            <Card padding="lg">
              <pre className="rounded-md bg-muted/50 p-3 text-xs whitespace-pre-wrap text-foreground">
                {artifacts.data.rca}
              </pre>
            </Card>
          ) : (
            <EmptyState hint="The diagnoser writes one when a cycle processes this cluster.">
              No RCA artifact yet.
            </EmptyState>
          )}
        </section>

        <LinkedClusters clusterId={clusterId} />

        <section>
          <SectionHeader title="Prompt diff" />
          <PromptDiff prompt={artifacts.data?.prompt ?? null} />
        </section>

        <section>
          <SectionHeader title="Experiment results" />
          <ExperimentTable clusterId={clusterId} />
        </section>

        <section>
          <SectionHeader title="Approval" />
          <Card>
            <div className="space-y-3">
              <p className="text-xs text-muted-foreground">
                Approve writes the fix bundle to the artifacts directory. Reject keeps the cluster
                open and records your reason. Dismiss closes it without shipping anything.
              </p>
              <div className="space-y-1">
                <label htmlFor="approval-reason" className="text-xs font-medium text-foreground">
                  Reason (optional)
                </label>
                <textarea
                  id="approval-reason"
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  placeholder="Why does this fix ship (or not)?"
                  rows={2}
                  className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring/40"
                />
              </div>
              <div className="space-y-1">
                <label htmlFor="feedback-tag" className="text-xs font-medium text-foreground">
                  Clustering feedback (optional, shapes the next cycle)
                </label>
                <select
                  id="feedback-tag"
                  value={feedbackTag}
                  onChange={(event) => setFeedbackTag(event.target.value as FeedbackTag | "")}
                  className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-ring/40"
                >
                  {FEEDBACK_TAG_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
              <ExperimentEvidence
                summary={experiment.data ?? null}
                isLoading={experiment.isLoading}
                isError={experiment.isError}
              />
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-xs text-muted-foreground">
                  Recording as <span className="font-mono">{reviewer.data?.reviewer ?? "..."}</span>
                  {reviewerIsAnonymous ? (
                    <>
                      <span aria-hidden="true" className="text-muted-foreground/40">
                        {" · "}
                      </span>
                      <span className="text-status-escalated">
                        no reviewer identity configured (set NENGOK_REVIEWER or
                        ~/.nengok/reviewer.txt)
                      </span>
                    </>
                  ) : null}
                </p>
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
            </div>
          </Card>
        </section>

        <section>
          <SectionHeader title="Approval history" />
          <ApprovalHistory clusterId={clusterId} />
        </section>

        <WrongMergePanel
          clusterId={clusterId}
          memberSpansJson={cluster.data.member_spans_json}
          onDetached={() => {
            queryClient.invalidateQueries({ queryKey: ["clusters"] });
          }}
        />
      </div>
    </div>
  );
}

function ClusterMetaRow({ cluster }: { cluster: Cluster }) {
  const memberCount = parseMemberSpans(cluster.member_spans_json).length;
  return (
    <div className="-mt-3 mb-6 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
      <span className="entity-id">{cluster.cluster_id}</span>
      <MetaDot />
      <span className="tabular-nums">
        {memberCount} member span{memberCount === 1 ? "" : "s"}
      </span>
      <MetaDot />
      <span>First seen {formatDateTime(cluster.created_at)}</span>
      <MetaDot />
      <span>Updated {formatDateTime(cluster.updated_at)}</span>
      {cluster.project ? <Badge tone="primary">{cluster.project}</Badge> : null}
    </div>
  );
}

function MetaDot() {
  return (
    <span aria-hidden="true" className="text-muted-foreground/40">
      ·
    </span>
  );
}

/**
 * Structured diagnosis from the diagnoser, shown before the prose RCA
 * so reviewers get the expected-vs-actual contrast they approve
 * against without reading the full artifact.
 */
function HypothesisCard({ hypothesis }: { hypothesis: RootCauseHypothesis }) {
  return (
    <section>
      <SectionHeader title="Hypothesis" />
      <Card padding="lg">
        <p className="text-sm text-foreground">{hypothesis.summary}</p>
        {hypothesis.expected_behavior || hypothesis.actual_behavior ? (
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            {hypothesis.expected_behavior ? (
              <div>
                <div className="section-label">Expected</div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {hypothesis.expected_behavior}
                </p>
              </div>
            ) : null}
            {hypothesis.actual_behavior ? (
              <div>
                <div className="section-label">Actual</div>
                <p className="mt-1 text-xs text-muted-foreground">{hypothesis.actual_behavior}</p>
              </div>
            ) : null}
          </div>
        ) : null}
        {hypothesis.likely_cause ? (
          <div className="mt-3">
            <div className="section-label">Likely cause</div>
            <p className="mt-1 text-xs text-muted-foreground">{hypothesis.likely_cause}</p>
          </div>
        ) : null}
        {hypothesis.implicated_tools.length > 0 ? (
          <div className="mt-3 flex flex-wrap gap-1">
            {hypothesis.implicated_tools.map((tool) => (
              <InlineCode key={tool}>{tool}</InlineCode>
            ))}
          </div>
        ) : null}
      </Card>
    </section>
  );
}

function ExperimentEvidence({
  summary,
  isLoading,
  isError,
}: {
  summary: ExperimentSummary | null;
  isLoading: boolean;
  isError: boolean;
}) {
  if (isLoading) {
    return null;
  }
  if (isError) {
    return <p className="text-xs text-muted-foreground">Experiment results unavailable.</p>;
  }
  if (!summary) {
    return <p className="text-xs text-muted-foreground">No experiment evidence yet.</p>;
  }
  const deltaClass =
    summary.fix_pass_rate > summary.baseline_pass_rate
      ? "text-status-fix"
      : summary.fix_pass_rate < summary.baseline_pass_rate
        ? "text-status-escalated"
        : "text-foreground";
  return (
    <p className="text-xs text-muted-foreground">
      Latest experiment: fix{" "}
      <span className={`font-medium tabular-nums ${deltaClass}`}>
        {formatPercent(summary.fix_pass_rate)}
      </span>{" "}
      vs baseline{" "}
      <span className="tabular-nums">{formatPercent(summary.baseline_pass_rate)}</span>, golden set{" "}
      <span className="tabular-nums">{formatPercent(summary.golden_fix_pass_rate)}</span>.
    </p>
  );
}

function parseHypothesis(json: string | null): RootCauseHypothesis | null {
  if (!json) {
    return null;
  }
  try {
    const parsed: unknown = JSON.parse(json);
    if (parsed === null || typeof parsed !== "object") {
      return null;
    }
    const candidate = parsed as Partial<RootCauseHypothesis>;
    if (typeof candidate.summary !== "string" || candidate.summary.length === 0) {
      return null;
    }
    return {
      summary: candidate.summary,
      expected_behavior:
        typeof candidate.expected_behavior === "string" ? candidate.expected_behavior : "",
      actual_behavior:
        typeof candidate.actual_behavior === "string" ? candidate.actual_behavior : "",
      likely_cause: typeof candidate.likely_cause === "string" ? candidate.likely_cause : "",
      implicated_tools: Array.isArray(candidate.implicated_tools)
        ? candidate.implicated_tools.map(String)
        : [],
    };
  } catch {
    return null;
  }
}

function ClusterDetailSkeleton() {
  return (
    <div className="p-8 animate-in fade-in duration-300">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div className="min-w-0 space-y-2">
          <Skeleton className="h-6 w-64" />
          <Skeleton className="h-4 w-96" />
        </div>
        <Skeleton className="h-8 w-24" />
      </div>
      <Skeleton className="-mt-3 mb-6 h-3 w-80" />
      <div className="space-y-8">
        <section>
          <Skeleton className="mb-3 h-3 w-32" />
          <Card padding="lg">
            <div className="space-y-2">
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-11/12" />
              <Skeleton className="h-3 w-4/5" />
            </div>
          </Card>
        </section>
        <section>
          <Skeleton className="mb-3 h-3 w-24" />
          <Card padding="md">
            <Skeleton className="h-24 w-full" />
          </Card>
        </section>
        <section>
          <Skeleton className="mb-3 h-3 w-32" />
          <Card padding="md">
            <Skeleton className="h-32 w-full" />
          </Card>
        </section>
      </div>
    </div>
  );
}
