import type { ReactNode } from "react";

interface EmptyStateProps {
  children: ReactNode;
  hint?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
}

/**
 * Dashed placeholder for sections with nothing to show yet. Renders a
 * plain div rather than Card so the dashed border does not stack on
 * Card's ring. With an icon it switches to the left-aligned banner
 * layout used on the overview page.
 */
export function EmptyState({ children, hint, action, icon }: EmptyStateProps) {
  if (icon) {
    return (
      <div className="flex items-start gap-3 rounded-xl border border-dashed border-border bg-card p-4">
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
          {icon}
        </div>
        <div className="flex-1">
          <p className="text-sm text-foreground">{children}</p>
          {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
          {action ? <div className="mt-1">{action}</div> : null}
        </div>
      </div>
    );
  }
  return (
    <div className="rounded-xl border border-dashed border-border bg-card p-6 text-center">
      <p className="text-sm text-muted-foreground">{children}</p>
      {hint ? <p className="mt-2 text-xs text-muted-foreground">{hint}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}
