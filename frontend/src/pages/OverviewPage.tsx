import { useQuery } from "@tanstack/react-query";
import { fetchClusters } from "../api/clusters";

export function OverviewPage() {
  const { data: clusters = [] } = useQuery({
    queryKey: ["clusters"],
    queryFn: () => fetchClusters(),
  });

  const open = clusters.filter((c) => c.status === "open" || c.status === "diagnosed").length;
  const fixed = clusters.filter((c) => c.status === "approved").length;
  const proposed = clusters.filter((c) => c.status === "fix_proposed").length;
  const escalated = clusters.filter((c) => c.status === "escalated").length;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Overview</h1>
        <p className="text-sm text-neutral-500 mt-1">
          Snapshot of every failure cluster Nengok has detected in this project.
        </p>
      </header>

      <div className="grid grid-cols-4 gap-4">
        <Stat label="Open clusters" value={open} accent="open" />
        <Stat label="Fix proposed" value={proposed} accent="diagnosed" />
        <Stat label="Approved" value={fixed} accent="fix" />
        <Stat label="Escalated" value={escalated} accent="escalated" />
      </div>
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
