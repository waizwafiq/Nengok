import { useQuery } from "@tanstack/react-query";
import { ChevronRight, CircleHelp, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { Link } from "react-router-dom";
import { fetchClusters } from "../../api/clusters";
import { useLayout } from "./useLayout";
import type { BreadcrumbItem } from "./useLayout";

export function TopBar() {
  const { sidebarCollapsed, toggleSidebar, breadcrumb } = useLayout();
  const clusters = useQuery({
    queryKey: ["clusters"],
    queryFn: () => fetchClusters(),
  });

  const openCount =
    clusters.data?.filter((c) => c.status === "open" || c.status === "diagnosed").length ?? 0;

  return (
    <header className="flex h-14 shrink-0 items-center justify-between px-4 text-sm text-sidebar-foreground">
      <div className="flex min-w-0 items-center gap-3">
        <button
          type="button"
          onClick={toggleSidebar}
          aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-pressed={!sidebarCollapsed}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-sidebar-foreground/60 transition-colors hover:bg-sidebar-foreground/10 hover:text-sidebar-foreground"
        >
          {sidebarCollapsed ? (
            <PanelLeftOpen className="h-4 w-4" />
          ) : (
            <PanelLeftClose className="h-4 w-4" />
          )}
        </button>

        <BreadcrumbTrail trail={breadcrumb} />
      </div>

      <div className="flex shrink-0 items-center gap-3">
        <StatusPill live={!clusters.isError} openCount={openCount} />
        <button
          type="button"
          aria-label="Help"
          className="flex h-8 w-8 items-center justify-center rounded-md text-sidebar-foreground/60 transition-colors hover:bg-sidebar-foreground/10 hover:text-sidebar-foreground"
        >
          <CircleHelp className="h-4 w-4" />
        </button>
      </div>
    </header>
  );
}

function BreadcrumbTrail({ trail }: { trail: BreadcrumbItem[] }) {
  if (trail.length === 0) {
    return null;
  }
  return (
    <nav
      aria-label="Breadcrumb"
      className="flex min-w-0 items-center gap-1 truncate text-xs text-sidebar-foreground/60"
    >
      {trail.map((item, index) => {
        const isLast = index === trail.length - 1;
        return (
          <span key={`${item.label}-${index}`} className="flex items-center gap-1">
            {index > 0 ? <ChevronRight className="h-3 w-3 text-sidebar-foreground/30" /> : null}
            {item.href && !isLast ? (
              <Link to={item.href} className="hover:text-sidebar-foreground transition-colors">
                {item.label}
              </Link>
            ) : (
              <span className={isLast ? "font-medium text-sidebar-foreground" : ""}>{item.label}</span>
            )}
          </span>
        );
      })}
    </nav>
  );
}

function StatusPill({ live, openCount }: { live: boolean; openCount: number }) {
  return (
    <div className="flex items-center gap-2 rounded-full bg-sidebar-foreground/5 px-2.5 py-1 text-[11px] text-sidebar-foreground/80">
      <StatusDot live={live} />
      <span>{openCount} active</span>
    </div>
  );
}

function StatusDot({ live }: { live: boolean }) {
  if (!live) {
    return (
      <span className="relative flex h-2 w-2">
        <span className="relative inline-flex h-2 w-2 rounded-full bg-status-escalated" />
      </span>
    );
  }
  return (
    <span className="relative flex h-2 w-2">
      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-status-fix/60" />
      <span className="relative inline-flex h-2 w-2 rounded-full bg-status-fix" />
    </span>
  );
}
