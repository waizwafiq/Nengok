import { useQuery } from "@tanstack/react-query";
import { fetchLatestExperiment } from "../../api/experiments";
import { Card } from "../ui/Card";
import type { ExperimentCase, ExperimentSummary } from "../../types/experiment";

interface Props {
  clusterId: string;
}

/**
 * Per-case experiment results for a cluster's latest run.
 *
 * Each row shows the input, output, and any evaluator scores
 * Phoenix returned. Columns are derived from the union of
 * evaluator keys across cases so a partial result doesn't
 * collapse the table.
 */
export function ExperimentTable({ clusterId }: Props) {
  const query = useQuery({
    queryKey: ["experiments", clusterId, "latest"],
    queryFn: () => fetchLatestExperiment(clusterId),
    enabled: Boolean(clusterId),
    retry: false,
  });

  if (query.isLoading) {
    return <p className="text-sm text-muted-foreground">Loading experiment…</p>;
  }

  if (query.isError) {
    return (
      <p className="text-sm text-destructive">
        Could not load the latest experiment for this cluster.
      </p>
    );
  }

  const data = query.data;
  if (!data) {
    return (
      <p className="text-sm text-muted-foreground">
        No experiment has been run for this cluster yet.
      </p>
    );
  }

  const evaluatorColumns = collectEvaluatorKeys(data.per_case);

  return (
    <div className="space-y-3">
      <PassRateSummary data={data} />
      <Card padding="none" className="overflow-x-auto">
        <table className="min-w-full text-xs">
          <thead className="bg-muted/40 text-muted-foreground uppercase tracking-wider">
            <tr>
              <th className="px-3 py-2 text-left font-semibold">Case</th>
              <th className="px-3 py-2 text-left font-semibold">Input</th>
              <th className="px-3 py-2 text-left font-semibold">Output</th>
              {evaluatorColumns.map((key) => (
                <th key={key} className="px-3 py-2 text-left font-semibold">
                  {key}
                </th>
              ))}
              <th className="px-3 py-2 text-left font-semibold">Passed</th>
            </tr>
          </thead>
          <tbody>
            {data.per_case.map((row, index) => (
              <tr key={row.case_id ?? index} className="border-t border-border align-top">
                <td className="px-3 py-2 font-mono text-foreground">
                  {row.case_id ?? `#${index + 1}`}
                </td>
                <td className="px-3 py-2 font-mono text-foreground max-w-xs truncate">
                  {jsonPreview(row.input)}
                </td>
                <td className="px-3 py-2 font-mono text-foreground max-w-xs truncate">
                  {jsonPreview(row.output)}
                </td>
                {evaluatorColumns.map((key) => (
                  <td key={key} className="px-3 py-2">
                    <EvaluatorCell value={row.evaluators?.[key]} />
                  </td>
                ))}
                <td className="px-3 py-2">
                  {row.passed === undefined ? (
                    <span className="text-muted-foreground">—</span>
                  ) : row.passed ? (
                    <span className="text-status-fix">✓</span>
                  ) : (
                    <span className="text-status-escalated">✗</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

function PassRateSummary({ data }: { data: ExperimentSummary }) {
  return (
    <div className="grid grid-cols-2 gap-3 text-xs lg:grid-cols-4">
      <PassRateCell label="Baseline" value={data.baseline_pass_rate} />
      <PassRateCell label="Fix" value={data.fix_pass_rate} />
      <PassRateCell label="Golden baseline" value={data.golden_baseline_pass_rate} />
      <PassRateCell label="Golden fix" value={data.golden_fix_pass_rate} />
    </div>
  );
}

function PassRateCell({ label, value }: { label: string; value: number }) {
  return (
    <Card padding="sm">
      <div className="section-label">{label}</div>
      <div className="mt-1 text-lg font-semibold tabular-nums text-foreground">
        {(value * 100).toFixed(0)}%
      </div>
    </Card>
  );
}

function EvaluatorCell({ value }: { value: boolean | number | string | undefined }) {
  if (value === undefined || value === null) {
    return <span className="text-muted-foreground">—</span>;
  }
  if (typeof value === "boolean") {
    return <span className={value ? "text-status-fix" : "text-status-escalated"}>{value ? "✓" : "✗"}</span>;
  }
  if (typeof value === "number") {
    return <span>{Number.isInteger(value) ? value : value.toFixed(2)}</span>;
  }
  return <span>{value}</span>;
}

function collectEvaluatorKeys(rows: ExperimentCase[]): string[] {
  const seen = new Set<string>();
  for (const row of rows) {
    const evaluators = row.evaluators;
    if (!evaluators) {
      continue;
    }
    for (const key of Object.keys(evaluators)) {
      seen.add(key);
    }
  }
  return Array.from(seen).sort();
}

function jsonPreview(value: unknown): string {
  if (value === undefined || value === null) {
    return "—";
  }
  if (typeof value === "string") {
    return value;
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}
