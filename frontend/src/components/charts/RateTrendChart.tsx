import { useState } from "react";
import type { KeyboardEvent, MouseEvent } from "react";
import { formatDay, formatPercent } from "../../lib/format";
import type { DuplicateRatePoint } from "../../types/dashboard";
import { ChartEmptyState } from "./ChartEmptyState";
import { ChartTooltip } from "./ChartTooltip";
import { CHART_MARGIN, linearScale, niceTicks } from "./chartScale";
import { InlineCode } from "../ui/InlineCode";
import { useContainerWidth } from "./useContainerWidth";

interface RateTrendChartProps {
  points: DuplicateRatePoint[];
  height?: number;
}

/**
 * Duplicate-rate trend over the last 30 days. The y domain is pinned
 * to at least 0-50% so day-to-day noise does not rescale the chart;
 * a falling line means activated clustering advice is reducing
 * identity merges. The capture rect is focusable: arrow keys step
 * through days, mirroring mouse hover.
 */
export function RateTrendChart({ points, height = 120 }: RateTrendChartProps) {
  const [ref, width] = useContainerWidth();
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  if (points.length === 0) {
    return (
      <ChartEmptyState
        height={height}
        message={
          <>
            No duplicate-rate data yet. Run <InlineCode>nengok improve</InlineCode> to start the
            trend.
          </>
        }
      />
    );
  }

  const plotLeft = CHART_MARGIN.left;
  const plotRight = Math.max(plotLeft + 1, width - CHART_MARGIN.right);
  const plotTop = CHART_MARGIN.top;
  const plotBottom = height - CHART_MARGIN.bottom;

  const maxRate = Math.max(...points.map((point) => point.rate));
  const ticks = niceTicks(Math.max(0.5, maxRate * 1.1));
  const yMax = ticks[ticks.length - 1] || 1;
  const x = linearScale(0, points.length - 1, plotLeft, plotRight);
  const y = linearScale(0, yMax, plotBottom, plotTop);

  const linePath = points
    .map(
      (point, index) =>
        `${index === 0 ? "M" : "L"}${x(index).toFixed(1)},${y(point.rate).toFixed(1)}`,
    )
    .join(" ");

  const lastIndex = points.length - 1;
  const middleIndex = Math.floor(lastIndex / 2);
  const hovered = hoverIndex !== null && hoverIndex < points.length ? points[hoverIndex] : null;

  function handleMouseMove(event: MouseEvent<SVGRectElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    const ratio = (event.clientX - box.left) / Math.max(1, box.width);
    const index = Math.round(ratio * lastIndex);
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
        aria-label={`Duplicate-rate trend, last ${points.length} days`}
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
              {formatPercent(tick)}
            </text>
          </g>
        ))}
        {points.length > 1 ? (
          <path
            d={linePath}
            fill="none"
            strokeWidth={1.5}
            className="stroke-status-diagnosed"
          />
        ) : null}
        <circle
          cx={x(lastIndex)}
          cy={y(points[lastIndex].rate)}
          r={2.5}
          className="fill-status-diagnosed"
        />
        <text
          x={plotLeft}
          y={height - 4}
          fontSize={10}
          textAnchor="start"
          className="fill-muted-foreground font-mono"
        >
          {formatDay(points[0].day)}
        </text>
        {middleIndex > 0 && middleIndex < lastIndex ? (
          <text
            x={x(middleIndex)}
            y={height - 4}
            fontSize={10}
            textAnchor="middle"
            className="fill-muted-foreground font-mono"
          >
            {formatDay(points[middleIndex].day)}
          </text>
        ) : null}
        {lastIndex > 0 ? (
          <text
            x={plotRight}
            y={height - 4}
            fontSize={10}
            textAnchor="end"
            className="fill-muted-foreground font-mono"
          >
            {formatDay(points[lastIndex].day)}
          </text>
        ) : null}
        {hovered !== null && hoverIndex !== null ? (
          <g>
            <line
              x1={x(hoverIndex)}
              x2={x(hoverIndex)}
              y1={plotTop}
              y2={plotBottom}
              strokeWidth={1}
              className="stroke-border"
            />
            <circle
              cx={x(hoverIndex)}
              cy={y(hovered.rate)}
              r={3}
              strokeWidth={1.5}
              className="fill-status-diagnosed stroke-card"
            />
          </g>
        ) : null}
        <rect
          x={plotLeft}
          y={plotTop}
          width={plotRight - plotLeft}
          height={plotBottom - plotTop}
          fill="transparent"
          tabIndex={0}
          aria-label="Duplicate-rate values; step through days with the left and right arrow keys"
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
          x={x(hoverIndex)}
          y={y(hovered.rate)}
          containerWidth={width}
          containerHeight={height}
        >
          <div className="text-muted-foreground">{formatDay(hovered.day)}</div>
          <div className="font-mono">{(hovered.rate * 100).toFixed(0)}% duplicates</div>
        </ChartTooltip>
      ) : null}
    </div>
  );
}
