import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

type StatSize = "sm" | "md" | "lg";

interface StatProps {
  label: string;
  value: ReactNode;
  size?: StatSize;
  hint?: ReactNode;
  valueClassName?: string;
  trailing?: ReactNode;
}

const SIZES: Record<StatSize, string> = {
  sm: "text-lg",
  md: "text-2xl",
  lg: "text-3xl",
};

/**
 * Label-over-value stat block rendered inside a Card. The three sizes
 * are the app's whole stat scale: lg for headline counts, md for
 * metric cards, sm for inline cells. Compose charts or legends as
 * siblings inside the same Card rather than extending this component.
 */
export function Stat({ label, value, size = "md", hint, valueClassName, trailing }: StatProps) {
  return (
    <div>
      <div className="section-label">{label}</div>
      <div className="mt-2 flex items-center justify-between gap-2">
        <div
          className={cn(SIZES[size], "font-semibold tabular-nums", valueClassName ?? "text-foreground")}
        >
          {value}
        </div>
        {trailing}
      </div>
      {hint ? <div className="mt-1 text-xs text-muted-foreground">{hint}</div> : null}
    </div>
  );
}
