import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { fetchDashboardOverview } from "../api/dashboard";
import { fetchClusters } from "../api/clusters";

export function OverviewPage() {
  const overview = useQuery({
    queryKey: ["dashboard", "overview"],
    queryFn: fetchDashboardOverview,
  });

  const clusters = useQuery({
    queryKey: ["clusters"],
    queryFn: () => fetchClusters(),
  });

  if (overview.isLoading) {
    return <p className="text-sm text-neutral-500">Loading overview…</p>;
  }

  if (overview.isError || !overview.data) {
    return (
      <p className="text-sm text-status-escalated">
        Could not load dashboard metrics. Is the Nengok server running?
      </p>
    );
  }

  const data = overview.data;
  const counts = data.cluster_counts;
  const totalClusters = clusters.data?.length ?? 0;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Overview</h1>
        <p className="text-sm text-neutral-500 mt-1">
          Snapshot of every failure cluster Nengok has detected in this project.
        </p>
      </header>

      {totalClusters === 0 ? <EmptyStateBanner /> : null}

      <section className="grid grid-cols-4 gap-4">
        <Stat label="Open clusters" value={counts.open + counts.diagnosed} accent="open" />
        <Stat label="Fix proposed" value={counts.fix_proposed} accent="diagnosed" />
        <Stat label="Approved" value={counts.approved} accent="fix" />
        <Stat label="Escalated" value={counts.escalated} accent="escalated" />
      </section>

      <section className="grid grid-cols-3 gap-4">
        <MetricCard
          label="Mean time to detect"
          value={formatDuration(data.mttd_seconds)}
          hint="First failing span to diagnosed cluster"
        />
        <MetricCard
          label="Mean time to resolve"
          value={formatDuration(data.mttr_seconds)}
          hint="Diagnosed cluster to approved fix"
        />
        <MetricCard
          label="Close rate"
          value={formatPercent(data.close_rate)}
          hint="Approved over open + diagnosed + escalated + approved"
        />
        <MetricCard
          label="Regression tests"
          value={data.regression_test_count.toString()}
          hint="Latest experiment per cluster, summed"
        />
        <MetricCard
          label="Fix pass rate (30d)"
          value={formatPercent(data.fix_pass_rate_30d)}
          hint="Average fix-prompt pass rate across recent experiments"
        />
      </section>
    </div>
  );
}

function Stat({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent: "open" | "diagnosed" | "fix" | "escalated";
}) {
  const accentClass = {
    open: "text-status-open",
    diagnosed: "text-status-diagnosed",
    fix: "text-status-fix",
    escalated: "text-status-escalated",
  }[accent];

  return (
    <div className="pane p-4">
      <div className="text-xs uppercase tracking-wide text-neutral-500">{label}</div>
      <div className={`mt-2 text-3xl font-semibold ${accentClass}`}>{value}</div>
    </div>
  );
}

function MetricCard({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="pane p-4 space-y-1">
      <div className="text-xs uppercase tracking-wide text-neutral-500">{label}</div>
      <div className="text-2xl font-semibold text-neutral-900">{value}</div>
      <div className="text-xs text-neutral-500">{hint}</div>
    </div>
  );
}

function EmptyStateBanner() {
  return (
    <div className="pane p-4 border border-dashed border-neutral-300 bg-neutral-50">
      <p className="text-sm text-neutral-700">
        No clusters yet. Seed Phoenix with{" "}
        <code className="font-mono text-xs">python -m sample_agent.agent --inject all</code>, then
        run <code className="font-mono text-xs">nengok run</code>.
      </p>
      <Link
        to="/clusters"
        className="mt-2 inline-block text-xs text-brand-primary hover:underline"
      >
        Open clusters view
      </Link>
    </div>
  );
}

function formatDuration(seconds: number | null): string {
  if (seconds === null || Number.isNaN(seconds)) {
    return "—";
  }
  if (seconds < 60) {
    return `${seconds.toFixed(0)}s`;
  }
  if (seconds < 3600) {
    return `${(seconds / 60).toFixed(1)}m`;
  }
  if (seconds < 86400) {
    return `${(seconds / 3600).toFixed(1)}h`;
  }
  return `${(seconds / 86400).toFixed(1)}d`;
}

function formatPercent(value: number | null): string {
  if (value === null || Number.isNaN(value)) {
    return "—";
  }
  return `${(value * 100).toFixed(0)}%`;
}
