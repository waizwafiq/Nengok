import { useQuery } from "@tanstack/react-query";
import { CircleHelp } from "lucide-react";
import { fetchClusters } from "../../api/clusters";

export function TopBar() {
  const clusters = useQuery({
    queryKey: ["clusters"],
    queryFn: () => fetchClusters(),
  });

  const openCount =
    clusters.data?.filter((c) => c.status === "open" || c.status === "diagnosed").length ?? 0;

  return (
    <header className="flex h-14 shrink-0 items-center justify-between px-6 text-sm text-white">
      <div className="flex items-center gap-3">
        <StatusDot live={!clusters.isError} />
        <span className="font-medium tracking-tight">Nengok</span>
        <span className="entity-id text-white/60">travel-planner-agent</span>
        <span className="rounded-full bg-white/10 px-2 py-0.5 text-[11px] font-medium text-white/80">
          {openCount} active
        </span>
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          aria-label="Help"
          className="flex h-8 w-8 items-center justify-center rounded-md text-white/60 transition-colors hover:bg-white/10 hover:text-white"
        >
          <CircleHelp className="h-4 w-4" />
        </button>
      </div>
    </header>
  );
}

function StatusDot({ live }: { live: boolean }) {
  if (!live) {
    return (
      <span className="relative flex h-2 w-2">
        <span className="relative inline-flex h-2 w-2 rounded-full bg-status-escalated" />
      </span>
    );
  }
  return (
    <span className="relative flex h-2 w-2">
      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-status-fix/60" />
      <span className="relative inline-flex h-2 w-2 rounded-full bg-status-fix" />
    </span>
  );
}
