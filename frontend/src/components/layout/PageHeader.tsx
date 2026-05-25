import { ChevronRight } from "lucide-react";
import type { ComponentType, ReactNode } from "react";

interface BreadcrumbItem {
  label: string;
  href?: string;
}

interface Props {
  icon?: ComponentType<{ className?: string }>;
  title: string;
  description?: string;
  breadcrumb?: BreadcrumbItem[];
  actions?: ReactNode;
}

export function PageHeader({ icon: Icon, title, description, breadcrumb, actions }: Props) {
  return (
    <div className="mb-7">
      {breadcrumb && breadcrumb.length > 0 ? <Breadcrumb trail={breadcrumb} /> : null}
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          {Icon ? (
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-border bg-card text-primary">
              <Icon className="h-5 w-5" />
            </div>
          ) : null}
          <div className="min-w-0">
            <h1 className="text-xl font-semibold tracking-tight text-foreground">{title}</h1>
            {description ? (
              <p className="mt-0.5 max-w-2xl text-sm text-muted-foreground">{description}</p>
            ) : null}
          </div>
        </div>
        {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
      </div>
    </div>
  );
}

function Breadcrumb({ trail }: { trail: BreadcrumbItem[] }) {
  return (
    <nav aria-label="Breadcrumb" className="mb-3 flex items-center gap-1 text-xs text-muted-foreground">
      {trail.map((item, index) => (
        <span key={`${item.label}-${index}`} className="flex items-center gap-1">
          {index > 0 ? <ChevronRight className="h-3 w-3 text-muted-foreground/60" /> : null}
          <span className={index === trail.length - 1 ? "text-foreground" : ""}>{item.label}</span>
        </span>
      ))}
    </nav>
  );
}
