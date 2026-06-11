import type { ReactNode } from "react";

interface ChartTooltipProps {
  x: number;
  y: number;
  containerWidth: number;
  containerHeight: number;
  children: ReactNode;
}

/**
 * Absolutely positioned tooltip for the SVG charts; the chart wrapper
 * must be `relative`. It flips left of the cursor near the right edge
 * (200px clearance covers the max-w-48 cap) and above the anchor in
 * the lower half, so it never escapes the parent Card's
 * overflow-hidden clip.
 */
export function ChartTooltip({ x, y, containerWidth, containerHeight, children }: ChartTooltipProps) {
  const left = Math.max(0, x > containerWidth - 200 ? x - 200 : x + 8);
  const flipUp = y > containerHeight / 2;
  return (
    <div
      className="pointer-events-none absolute z-10 max-w-48 rounded-md border border-border bg-popover px-2 py-1.5 text-[11px] leading-4 text-popover-foreground shadow-md"
      style={flipUp ? { left, bottom: containerHeight - y + 8 } : { left, top: y + 8 }}
    >
      {children}
    </div>
  );
}
