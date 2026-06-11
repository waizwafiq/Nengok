import { useState } from "react";
import type { KeyboardEvent, MouseEvent } from "react";
import { cn } from "../../lib/cn";
import { formatDateTime, formatDay, formatDollars, formatTokenCount } from "../../lib/format";
import type { RecentCycle } from "../../types/dashboard";
import { ChartEmptyState } from "./ChartEmptyState";
import { ChartTooltip } from "./ChartTooltip";
import { CHART_MARGIN, linearScale, niceTicks } from "./chartScale";
import { CYCLE_STATUS_FILL_CLASS, CYCLE_STATUS_LABEL } from "./cycleStatus";
import { useContainerWidth } from "./useContainerWidth";

interface CycleCostBarsProps {
  cycles: RecentCycle[];
  height?: number;
}

/**
 * Gemini cost per cycle, oldest first, with each bar colored by the
 * cycle's outcome. The adjacent cycle-outcomes card doubles as the
 * color legend, so this chart renders none of its own. The capture
 * rect is focusable: arrow keys step through cycles, mirroring mouse
 * hover, and the tooltip carries the per-cycle cost, tokens, and
 * cluster counts.
 */
export function CycleCostBars({ cycles, height = 120 }: CycleCostBarsProps) {
  const [ref, width] = useContainerWidth();
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  if (cycles.length === 0) {
    return <ChartEmptyState height={height} message="No cycles recorded yet." />;
  }

  const plotLeft = CHART_MARGIN.left;
  const plotRight = Math.max(plotLeft + 1, width - CHART_MARGIN.right);
  const plotTop = CHART_MARGIN.top;
  const plotBottom = height - CHART_MARGIN.bottom;

  const ticks = niceTicks(Math.max(...cycles.map((cycle) => cycle.gemini_dollars)));
  const yMax = ticks[ticks.length - 1] || 1;
  const y = linearScale(0, yMax, plotBottom, plotTop);

  const slot = (plotRight - plotLeft) / cycles.length;
  const barWidth = Math.max(4, Math.min(28, slot - 4));
  const barX = (index: number) => plotLeft + index * slot + (slot - barWidth) / 2;

  const lastIndex = cycles.length - 1;
  const hovered = hoverIndex !== null && hoverIndex < cycles.length ? cycles[hoverIndex] : null;

  function handleMouseMove(event: MouseEvent<SVGRectElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    const index = Math.floor((event.clientX - box.left) / Math.max(1, slot));
    setHoverIndex(Math.min(lastIndex, Math.max(0, index)));
  }

  function handleKeyDown(event: KeyboardEvent<SVGRectElement>) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") {
      return;
    }
    event.preventDefault();
    const delta = event.key === "ArrowLeft" ? -1 : 1;
    setHoverIndex((current) =>
      Math.min(lastIndex, Math.max(0, (current ?? lastIndex) + delta)),
    );
  }

  return (
    <div ref={ref} className="relative">
      <svg
        width={width}
        height={height}
        role="img"
        aria-label={`Gemini cost for the last ${cycles.length} cycles`}
      >
        {ticks.map((tick) => (
          <g key={tick}>
            <line
              x1={plotLeft}
              x2={plotRight}
              y1={y(tick)}
              y2={y(tick)}
              strokeWidth={1}
              className="stroke-border"
            />
            <text
              x={plotLeft - 4}
              y={y(tick) + 3}
              fontSize={10}
              textAnchor="end"
              className="fill-muted-foreground font-mono"
            >
              {formatDollars(tick)}
            </text>
          </g>
        ))}
        {cycles.map((cycle, index) => {
          const barHeight = Math.max(2, plotBottom - y(cycle.gemini_dollars));
          return (
            <rect
              key={cycle.cycle_id}
              x={barX(index)}
              y={plotBottom - barHeight}
              width={barWidth}
              height={barHeight}
              rx={1.5}
              className={cn(
                CYCLE_STATUS_FILL_CLASS[cycle.status],
                hoverIndex !== null && hoverIndex !== index && "opacity-50",
              )}
            />
          );
        })}
        <text
          x={plotLeft}
          y={height - 4}
          fontSize={10}
          textAnchor="start"
          className="fill-muted-foreground font-mono"
        >
          {formatDay(cycles[0].started_at)}
        </text>
        {lastIndex > 0 ? (
          <text
            x={plotRight}
            y={height - 4}
            fontSize={10}
            textAnchor="end"
            className="fill-muted-foreground font-mono"
          >
            {formatDay(cycles[lastIndex].started_at)}
          </text>
        ) : null}
        <rect
          x={plotLeft}
          y={plotTop}
          width={plotRight - plotLeft}
          height={plotBottom - plotTop}
          fill="transparent"
          tabIndex={0}
          aria-label="Per-cycle cost details; step through cycles with the left and right arrow keys"
          className="outline-none focus-visible:stroke-ring"
          strokeWidth={1.5}
          onMouseMove={handleMouseMove}
          onMouseLeave={() => setHoverIndex(null)}
          onKeyDown={handleKeyDown}
          onFocus={() => setHoverIndex(lastIndex)}
          onBlur={() => setHoverIndex(null)}
        />
      </svg>
      {hovered !== null && hoverIndex !== null ? (
        <ChartTooltip
          x={barX(hoverIndex) + barWidth / 2}
          y={y(hovered.gemini_dollars)}
          containerWidth={width}
          containerHeight={height}
        >
          <div className="text-muted-foreground">{formatDateTime(hovered.started_at)}</div>
          <div>{CYCLE_STATUS_LABEL[hovered.status]}</div>
          <div className="font-mono">
            {formatDollars(hovered.gemini_dollars)} · {formatTokenCount(hovered.gemini_tokens)}{" "}
            tokens
          </div>
          <div>
            {hovered.clusters_processed} processed · {hovered.clusters_discovered} discovered
          </div>
        </ChartTooltip>
      ) : null}
    </div>
  );
}
