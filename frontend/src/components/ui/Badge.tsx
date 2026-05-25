import type { ReactNode } from "react";

type Tone = "neutral" | "open" | "diagnosed" | "fix" | "escalated" | "dismissed";

interface Props {
  children: ReactNode;
  tone?: Tone;
}

const TONES: Record<Tone, string> = {
  neutral: "bg-neutral-100 text-neutral-700 border-neutral-200",
  open: "bg-status-open/10 text-status-open border-status-open/30",
  diagnosed: "bg-status-diagnosed/10 text-status-diagnosed border-status-diagnosed/30",
  fix: "bg-status-fix/10 text-status-fix border-status-fix/30",
  escalated: "bg-status-escalated/10 text-status-escalated border-status-escalated/30",
  dismissed: "bg-status-dismissed/10 text-status-dismissed border-status-dismissed/30",
};

export function Badge({ children, tone = "neutral" }: Props) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border ${TONES[tone]}`}
    >
      {children}
    </span>
  );
}
