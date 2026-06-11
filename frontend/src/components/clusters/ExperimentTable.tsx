import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { fetchLatestExperiment } from "../../api/experiments";
import { cn } from "../../lib/cn";
import { caseKey } from "../../lib/experimentHelpers";
import { CaseOutcomeStrip } from "../charts/CaseOutcomeStrip";
import { PassRateComparison } from "../charts/PassRateComparison";
import { Card } from "../ui/Card";
import { EmptyState } from "../ui/EmptyState";
import { ErrorState } from "../ui/ErrorState";
import { InlineCode } from "../ui/InlineCode";
import { Skeleton } from "../ui/Skeleton";
import type { ExperimentCase } from "../../types/experiment";

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
  const [hoveredCaseId, setHoveredCaseId] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["experiments", clusterId, "latest"],
    queryFn: () => fetchLatestExperiment(clusterId),
    enabled: Boolean(clusterId),
    retry: false,
  });

  if (query.isLoading) {
    return <ExperimentTableSkeleton />;
  }

  if (query.isError) {
    return (
      <ErrorState
        title="Could not load the latest experiment for this cluster."
        hint={
          <>
            Re-run the cycle with <InlineCode>nengok run</InlineCode> to generate a fresh
            experiment.
          </>
        }
      />
    );
  }

  const data = query.data;
  if (!data) {
    return (
      <EmptyState
        hint={
          <>
            Trigger one with <InlineCode>nengok run</InlineCode>.
          </>
        }
      >
        No experiment has been run for this cluster yet.
      </EmptyState>
    );
  }

  const evaluatorColumns = collectEvaluatorKeys(data.per_case);

  return (
    <div className="space-y-3">
      <PassRateComparison summary={data} />
      <CaseOutcomeStrip
        cases={data.per_case}
        hoveredCaseId={hoveredCaseId}
        onHover={setHoveredCaseId}
      />
      <Card padding="none" className="overflow-x-auto">
        <table className="min-w-full text-xs">
          <thead className="bg-muted/40">
            <tr>
              <th className="section-label px-3 py-2 text-left">Case</th>
              <th className="section-label px-3 py-2 text-left">Input</th>
              <th className="section-label px-3 py-2 text-left">Output</th>
              {evaluatorColumns.map((key) => (
                <th key={key} className="section-label px-3 py-2 text-left">
                  {key}
                </th>
              ))}
              <th className="section-label px-3 py-2 text-left">Passed</th>
            </tr>
          </thead>
          <tbody>
            {data.per_case.map((row, index) => {
              const key = caseKey(row, index);
              return (
                <tr
                  key={key}
                  onMouseEnter={() => setHoveredCaseId(key)}
                  onMouseLeave={() => setHoveredCaseId(null)}
                  className={cn(
                    "border-t border-border align-top",
                    hoveredCaseId === key && "bg-muted/40",
                  )}
                >
                  <td className="px-3 py-2 font-mono text-foreground">{key}</td>
                  <td className="px-3 py-2 font-mono text-foreground max-w-xs truncate">
                    {jsonPreview(row.input)}
                  </td>
                  <td className="px-3 py-2 font-mono text-foreground max-w-xs truncate">
                    {jsonPreview(row.output)}
                  </td>
                  {evaluatorColumns.map((column) => (
                    <td key={column} className="px-3 py-2">
                      <EvaluatorCell value={row.evaluators?.[column]} />
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
              );
            })}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

function EvaluatorCell({ value }: { value: boolean | number | string | undefined }) {
  if (value === undefined || value === null) {
    return <span className="text-muted-foreground">—</span>;
  }
  if (typeof value === "boolean") {
    return (
      <span className={value ? "text-status-fix" : "text-status-escalated"}>
        {value ? "✓" : "✗"}
      </span>
    );
  }
  if (typeof value === "number") {
    return <span>{Number.isInteger(value) ? value : value.toFixed(2)}</span>;
  }
  return <span>{value}</span>;
}

function ExperimentTableSkeleton() {
  return (
    <div className="space-y-3">
      <Card>
        <div className="space-y-4">
          {Array.from({ length: 2 }).map((_, index) => (
            <div key={index}>
              <Skeleton className="h-3 w-24" />
              <Skeleton className="mt-2 h-2.5 w-full" />
              <Skeleton className="mt-1.5 h-2.5 w-full" />
            </div>
          ))}
        </div>
      </Card>
      <Card padding="md">
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-4 w-full" />
          ))}
        </div>
      </Card>
    </div>
  );
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
