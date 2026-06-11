import type { ReactNode } from "react";

interface ChartEmptyStateProps {
  height: number;
  message: ReactNode;
}

/**
 * Same-height stand-in for a chart with no data, so cards keep their
 * layout before the first cycle runs.
 */
export function ChartEmptyState({ height, message }: ChartEmptyStateProps) {
  return (
    <div className="relative flex items-center justify-center" style={{ height }}>
      <div
        className="absolute inset-x-0 top-1/2 border-t border-dashed border-muted-foreground/30"
        aria-hidden="true"
      />
      <p className="relative bg-card px-2 text-xs text-muted-foreground">{message}</p>
    </div>
  );
}
