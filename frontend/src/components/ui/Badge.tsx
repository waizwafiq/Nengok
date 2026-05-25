import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

type Tone =
  | "neutral"
  | "primary"
  | "open"
  | "diagnosed"
  | "fix"
  | "escalated"
  | "dismissed";

interface Props {
  children: ReactNode;
  tone?: Tone;
  className?: string;
}

const TONES: Record<Tone, string> = {
  neutral: "bg-muted text-muted-foreground",
  primary: "bg-primary/10 text-primary",
  open: "bg-status-open/15 text-status-open",
  diagnosed: "bg-status-diagnosed/15 text-status-diagnosed",
  fix: "bg-status-fix/15 text-status-fix",
  escalated: "bg-status-escalated/15 text-status-escalated",
  dismissed: "bg-status-dismissed/15 text-status-dismissed",
};

export function Badge({ children, tone = "neutral", className }: Props) {
  return (
    <span
      className={cn(
        "inline-flex h-5 w-fit shrink-0 items-center justify-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
