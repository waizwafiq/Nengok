/**
 * Tiny SVG sparkline for a numeric series.
 *
 * Renders a polyline scaled to the component's box. An empty series
 * renders a flat baseline so the card layout stays stable when there
 * is no data yet.
 */

interface SparklineProps {
  values: number[];
  width?: number;
  height?: number;
  strokeClassName?: string;
}

export function Sparkline({
  values,
  width = 96,
  height = 24,
  strokeClassName = "stroke-primary",
}: SparklineProps) {
  if (values.length === 0) {
    return (
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden>
        <line
          x1={0}
          x2={width}
          y1={height / 2}
          y2={height / 2}
          className="stroke-muted-foreground/30"
          strokeWidth={1}
        />
      </svg>
    );
  }

  const max = Math.max(...values, 0);
  const min = Math.min(...values, 0);
  const range = max - min || 1;
  const step = values.length > 1 ? width / (values.length - 1) : width;

  const points = values
    .map((value, index) => {
      const x = index * step;
      const y = height - ((value - min) / range) * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden>
      <polyline points={points} fill="none" strokeWidth={1.5} className={strokeClassName} />
    </svg>
  );
}
