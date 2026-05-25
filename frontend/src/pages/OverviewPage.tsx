import { useQuery } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { Link } from "react-router-dom";
import { fetchDashboardOverview } from "../api/dashboard";
import { fetchClusters } from "../api/clusters";
import { PageHeader } from "../components/layout/PageHeader";
import { useLayoutBreadcrumb } from "../components/layout/useLayout";
import { Card } from "../components/ui/Card";
import { Skeleton } from "../components/ui/Skeleton";

export function OverviewPage() {
  useLayoutBreadcrumb([{ label: "Workspace" }, { label: "Overview" }]);

  const overview = useQuery({
    queryKey: ["dashboard", "overview"],
    queryFn: fetchDashboardOverview,
  });

  const clusters = useQuery({
    queryKey: ["clusters"],
    queryFn: () => fetchClusters(),
  });

  if (overview.isLoading) {
    return (
      <div className="p-8 animate-in fade-in duration-300">
        <PageHeader
          title="Portfolio overview"
          description="Every failure cluster Nengok has detected in this project, plus the ones already fixed."
        />
        <section className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <Card key={index}>
              <Skeleton className="h-3 w-24" />
              <Skeleton className="mt-3 h-8 w-16" />
            </Card>
          ))}
        </section>
        <section className="mb-3">
          <Skeleton className="h-3 w-16" />
        </section>
        <section className="grid grid-cols-2 gap-4 lg:grid-cols-3">
          {Array.from({ length: 5 }).map((_, index) => (
            <Card key={index}>
              <Skeleton className="h-3 w-32" />
              <Skeleton className="mt-3 h-7 w-20" />
              <Skeleton className="mt-2 h-3 w-40" />
            </Card>
          ))}
        </section>
      </div>
    );
  }

  if (overview.isError || !overview.data) {
    return (
      <div className="p-8 animate-in fade-in duration-300">
        <PageHeader
          title="Portfolio overview"
          description="Every failure cluster Nengok has detected in this project, plus the ones already fixed."
        />
        <Card padding="lg">
          <p className="text-sm text-destructive">
            Could not load dashboard metrics. Is the Nengok server running?
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            Start it with{" "}
            <code className="font-mono text-xs rounded bg-muted px-1.5 py-0.5">
              nengok dashboard
            </code>{" "}
            and reload this page.
          </p>
        </Card>
      </div>
    );
  }

  const data = overview.data;
  const counts = data.cluster_counts;
  const totalClusters = clusters.data?.length ?? 0;

  return (
    <div className="p-8 animate-in fade-in duration-300">
      <PageHeader
        title="Portfolio overview"
        description="Every failure cluster Nengok has detected in this project, plus the ones already fixed."
      />

      {totalClusters === 0 ? <EmptyStateBanner /> : null}

      <section className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatTile label="Open clusters" value={counts.open + counts.diagnosed} accent="open" />
        <StatTile label="Fix proposed" value={counts.fix_proposed} accent="diagnosed" />
        <StatTile label="Approved" value={counts.approved} accent="fix" />
        <StatTile label="Escalated" value={counts.escalated} accent="escalated" />
      </section>

      <section className="mb-3 flex items-center justify-between">
        <h2 className="section-label">Health</h2>
      </section>

      <section className="grid grid-cols-2 gap-4 lg:grid-cols-3">
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
          hint="Approved over active total"
        />
        <MetricCard
          label="Regression tests"
          value={data.regression_test_count.toString()}
          hint="Latest experiment per cluster, summed"
        />
        <MetricCard
          label="Fix pass rate (30d)"
          value={formatPercent(data.fix_pass_rate_30d)}
          hint="Average across recent experiments"
        />
      </section>
    </div>
  );
}

function StatTile({
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
    <Card>
      <div className="section-label">{label}</div>
      <div className={`mt-2 text-3xl font-semibold tabular-nums ${accentClass}`}>{value}</div>
    </Card>
  );
}

function MetricCard({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <Card>
      <div className="section-label">{label}</div>
      <div className="mt-2 text-2xl font-semibold tabular-nums text-foreground">{value}</div>
      <div className="mt-1 text-xs text-muted-foreground">{hint}</div>
    </Card>
  );
}

function EmptyStateBanner() {
  return (
    <div className="mb-6 flex items-start gap-3 rounded-xl border border-dashed border-border bg-card p-4">
      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
        <Sparkles className="h-4 w-4" />
      </div>
      <div className="flex-1">
        <p className="text-sm text-foreground">
          No clusters yet. Seed Phoenix with{" "}
          <code className="font-mono text-xs rounded bg-muted px-1.5 py-0.5">
            python -m sample_agent.agent --inject all
          </code>
          , then run <code className="font-mono text-xs rounded bg-muted px-1.5 py-0.5">nengok run</code>.
        </p>
        <Link
          to="/clusters"
          className="mt-1 inline-block text-xs font-medium text-primary hover:underline"
        >
          Open clusters view
        </Link>
      </div>
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
