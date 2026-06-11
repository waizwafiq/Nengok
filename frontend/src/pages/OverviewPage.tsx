import { useQuery } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { Link } from "react-router-dom";
import { fetchDashboardOverview } from "../api/dashboard";
import { fetchClusters } from "../api/clusters";
import { AdvicePanel } from "../components/AdvicePanel";
import { CycleCostBars } from "../components/charts/CycleCostBars";
import { RateTrendChart } from "../components/charts/RateTrendChart";
import { SpendAreaChart } from "../components/charts/SpendAreaChart";
import { StatusDistributionBar } from "../components/charts/StatusDistributionBar";
import {
  CYCLE_STATUS_BAR_CLASS,
  CYCLE_STATUS_LABEL,
  CYCLE_STATUS_ORDER,
} from "../components/charts/cycleStatus";
import { PageHeader } from "../components/layout/PageHeader";
import { SectionHeader } from "../components/layout/SectionHeader";
import { useLayoutBreadcrumb } from "../components/layout/useLayout";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorState, RestartServerHint } from "../components/ui/ErrorState";
import { InlineCode } from "../components/ui/InlineCode";
import { Skeleton } from "../components/ui/Skeleton";
import { Stat } from "../components/ui/Stat";
import {
  formatDateTime,
  formatDollars,
  formatDuration,
  formatPercent,
  formatTokenCount,
} from "../lib/format";
import type {
  ClusteringQuality,
  GeminiSpendPoint,
  RecentCycle,
  RecentCycleStatusCounts,
} from "../types/dashboard";

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
    return <OverviewSkeleton />;
  }

  if (overview.isError || !overview.data) {
    return (
      <div className="p-8 animate-in fade-in duration-300">
        <PageHeader
          title="Portfolio overview"
          description="Every failure cluster Nengok has detected in this project, plus the ones already fixed."
        />
        <ErrorState
          title="Could not load dashboard metrics. Is the Nengok server running?"
          hint={<RestartServerHint />}
        />
      </div>
    );
  }

  const data = overview.data;
  const counts = data.cluster_counts;
  const totalClusters = clusters.data?.length ?? 0;
  const countsTotal = Object.values(counts).reduce((sum, count) => sum + count, 0);

  return (
    <div className="p-8 animate-in fade-in duration-300">
      <PageHeader
        title="Portfolio overview"
        description="Every failure cluster Nengok has detected in this project, plus the ones already fixed."
      />

      <div className="space-y-8">
        {clusters.isSuccess && totalClusters === 0 ? <SeedBanner /> : null}

        <section>
          <SectionHeader title="Pipeline" />
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StatTile label="Open clusters" value={counts.open + counts.diagnosed} accent="open" />
            <StatTile label="Fix proposed" value={counts.fix_proposed} accent="diagnosed" />
            <StatTile label="Approved" value={counts.approved} accent="fix" />
            <StatTile label="Escalated" value={counts.escalated} accent="escalated" />
          </div>
          {countsTotal > 0 ? (
            <Card className="mt-4">
              <StatusDistributionBar counts={counts} />
            </Card>
          ) : null}
        </section>

        <section>
          <SectionHeader title="Health" />
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-3">
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
          </div>
          <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
            <CostCard
              dollars={data.gemini_dollars_used_30d ?? 0}
              tokens={data.gemini_tokens_used_30d ?? 0}
              sparkline={data.gemini_spend_sparkline_30d ?? []}
            />
            <ClusteringQualityCard
              quality={
                data.clustering_quality ?? { duplicate_rate_trend: [], latest_golden_f1: null }
              }
            />
          </div>
        </section>

        <section>
          <SectionHeader title="Recent cycles" />
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <CycleSpendCard cycles={data.recent_cycles ?? []} />
            <CycleStatusCard
              counts={data.recent_cycle_status_counts ?? {}}
              cycles={data.recent_cycles ?? []}
            />
          </div>
        </section>

        <AdvicePanel />
      </div>
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
      <Stat size="lg" label={label} value={value} valueClassName={accentClass} />
    </Card>
  );
}

function MetricCard({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <Card>
      <Stat label={label} value={value} hint={hint} />
    </Card>
  );
}

function CostCard({
  dollars,
  tokens,
  sparkline,
}: {
  dollars: number;
  tokens: number;
  sparkline: GeminiSpendPoint[];
}) {
  return (
    <Card>
      <Stat
        label="Gemini spend (30d)"
        value={formatDollars(dollars)}
        hint={`${formatTokenCount(tokens)} tokens`}
      />
      <div className="mt-3">
        <SpendAreaChart points={sparkline} />
      </div>
    </Card>
  );
}

/**
 * Clustering quality: latest golden-set pairwise F1 from `nengok improve
 * --dry-run`, with the 30-day duplicate-rate trend (identity merges per
 * discovered cluster) charted below. All math happens server-side.
 */
function ClusteringQualityCard({ quality }: { quality: ClusteringQuality }) {
  const rates = quality.duplicate_rate_trend.map((point) => point.rate);
  const latestRate = rates.length > 0 ? rates[rates.length - 1] : null;
  return (
    <Card>
      <Stat
        label="Clustering quality"
        value={quality.latest_golden_f1 !== null ? quality.latest_golden_f1.toFixed(2) : "—"}
        hint={`Golden-set F1${
          latestRate !== null ? ` · duplicate rate ${(latestRate * 100).toFixed(0)}%` : ""
        }`}
      />
      <div className="mt-3">
        <RateTrendChart points={quality.duplicate_rate_trend} />
      </div>
    </Card>
  );
}

function CycleSpendCard({ cycles }: { cycles: RecentCycle[] }) {
  const ordered = [...cycles].reverse();
  const latest = cycles[0];
  const total = cycles.reduce((sum, cycle) => sum + cycle.gemini_dollars, 0);
  return (
    <Card>
      <Stat
        label={`Cost of last ${cycles.length || "—"} cycle${cycles.length === 1 ? "" : "s"}`}
        value={latest ? formatDollars(latest.gemini_dollars) : "—"}
        hint={
          latest
            ? `Latest cycle ${formatDateTime(latest.started_at)} · ${formatDollars(total)} total`
            : undefined
        }
      />
      <div className="mt-3">
        <CycleCostBars cycles={ordered} />
      </div>
    </Card>
  );
}

function CycleStatusCard({
  counts,
  cycles,
}: {
  counts: RecentCycleStatusCounts;
  cycles: RecentCycle[];
}) {
  const entries = CYCLE_STATUS_ORDER.map((status) => ({
    status,
    value: counts[status] ?? 0,
  }));
  const total = entries.reduce((sum, entry) => sum + entry.value, 0);
  const chronological = [...cycles].reverse();
  return (
    <Card>
      <div className="section-label">Cycle outcomes (last {total || "—"})</div>
      {chronological.length > 0 ? (
        <div className="mt-2 flex flex-wrap items-center gap-1">
          {chronological.map((cycle) => (
            <span
              key={cycle.cycle_id}
              role="img"
              aria-label={`${formatDateTime(cycle.started_at)}: ${CYCLE_STATUS_LABEL[cycle.status]}`}
              className={`h-2.5 w-2.5 rounded-full ${CYCLE_STATUS_BAR_CLASS[cycle.status]}`}
              title={`${formatDateTime(cycle.started_at)} · ${CYCLE_STATUS_LABEL[cycle.status]}`}
            />
          ))}
          <span className="ml-1 font-mono text-[10px] text-muted-foreground">now</span>
        </div>
      ) : null}
      <div className="mt-3 space-y-2">
        {entries.map((entry) => (
          <CycleStatusRow
            key={entry.status}
            label={CYCLE_STATUS_LABEL[entry.status]}
            value={entry.value}
            total={total}
            barClassName={CYCLE_STATUS_BAR_CLASS[entry.status]}
          />
        ))}
      </div>
    </Card>
  );
}

function CycleStatusRow({
  label,
  value,
  total,
  barClassName,
}: {
  label: string;
  value: number;
  total: number;
  barClassName: string;
}) {
  const width = total === 0 ? 0 : (value / total) * 100;
  return (
    <div>
      <div className="flex items-baseline justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="tabular-nums text-foreground">{value}</span>
      </div>
      <div className="mt-1 h-2 rounded bg-muted">
        <div
          className={`h-full rounded ${barClassName}`}
          style={{ width: `${width}%` }}
          aria-hidden
        />
      </div>
    </div>
  );
}

function SeedBanner() {
  return (
    <EmptyState
      icon={<Sparkles className="h-4 w-4" />}
      action={
        <Link
          to="/clusters"
          className="inline-block text-xs font-medium text-primary hover:underline"
        >
          Open clusters view
        </Link>
      }
    >
      No clusters yet. Seed Phoenix with{" "}
      <InlineCode>python -m sample_agent.agent --inject all</InlineCode>, then run{" "}
      <InlineCode>nengok run</InlineCode>.
    </EmptyState>
  );
}

function OverviewSkeleton() {
  return (
    <div className="p-8 animate-in fade-in duration-300">
      <PageHeader
        title="Portfolio overview"
        description="Every failure cluster Nengok has detected in this project, plus the ones already fixed."
      />
      <div className="space-y-8">
        <section>
          <Skeleton className="mb-3 h-3 w-16" />
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, index) => (
              <Card key={index}>
                <Skeleton className="h-3 w-24" />
                <Skeleton className="mt-3 h-9 w-16" />
              </Card>
            ))}
          </div>
        </section>
        <section>
          <Skeleton className="mb-3 h-3 w-16" />
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-3">
            {Array.from({ length: 5 }).map((_, index) => (
              <Card key={index}>
                <Skeleton className="h-3 w-32" />
                <Skeleton className="mt-3 h-8 w-20" />
                <Skeleton className="mt-2 h-3 w-40" />
              </Card>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
