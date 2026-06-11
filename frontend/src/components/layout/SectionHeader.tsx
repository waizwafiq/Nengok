import type { ReactNode } from "react";

/**
 * Page-section heading. Section labels always sit outside the card
 * they describe; cards contain only content. The mb-3 gap is the one
 * label-to-body distance used across the app.
 */
export function SectionHeader({ title, actions }: { title: string; actions?: ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between gap-3">
      <h2 className="section-label">{title}</h2>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  );
}
