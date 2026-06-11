import type { ComponentProps } from "react";
import { Link } from "react-router-dom";
import { cn } from "../../lib/cn";

/**
 * Button-shaped router link for navigation actions (View, Back to
 * clusters). Matches the sm outline Button, including its
 * focus-visible ring, so links and buttons in the same row share one
 * control style.
 */
export function LinkButton({ className, children, ...rest }: ComponentProps<typeof Link>) {
  return (
    <Link
      {...rest}
      className={cn(
        "inline-flex h-7 shrink-0 items-center justify-center gap-1 rounded-md border border-border bg-background px-2.5 text-xs font-medium whitespace-nowrap text-foreground transition-all outline-none select-none",
        "hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50 active:translate-y-px",
        "[&_svg]:pointer-events-none [&_svg]:shrink-0",
        className,
      )}
    >
      {children}
    </Link>
  );
}
