import { NavLink } from "react-router-dom";
import { Activity, LayoutDashboard } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "../../lib/cn";
import { useLayout } from "./useLayout";
import logoFull from "../../assets/nengok-logo.png";
import logoMark from "../../assets/nengok-logoonly.png";

const COLLAPSE_TRANSITION = "transition-all duration-200 ease-out";

/**
 * Owned by the layout shell so individual pages do not redraw the nav
 * on route changes. Add new top-level destinations here, not in
 * DashboardLayout.
 */
export function Header() {
  const { sidebarCollapsed } = useLayout();

  return (
    <div className="flex h-full min-w-0 flex-col overflow-hidden">
      <div className="flex h-14 items-center pl-4 pr-3">
        <div className="relative flex h-20 w-24 shrink-0 items-center justify-start">
          <img
            src={logoMark}
            alt=""
            aria-hidden="true"
            className={cn(
              "absolute left-0 top-1/2 h-7 w-7 -translate-y-1/2",
              COLLAPSE_TRANSITION,
              sidebarCollapsed ? "opacity-100" : "opacity-0",
            )}
          />
          <img
            src={logoFull}
            alt="Nengok"
            className={cn(
              "absolute left-0 top-1/2 h-14 -translate-y-1/2",
              COLLAPSE_TRANSITION,
              sidebarCollapsed ? "opacity-0" : "opacity-100",
            )}
          />
        </div>
      </div>

      <nav className="flex flex-col gap-4 px-3 pt-4" aria-label="Primary">
        <NavGroup label="Workspace" collapsed={sidebarCollapsed}>
          <NavItem
            to="/overview"
            icon={<LayoutDashboard className="h-4 w-4" />}
            label="Overview"
            collapsed={sidebarCollapsed}
          />
          <NavItem
            to="/clusters"
            icon={<Activity className="h-4 w-4" />}
            label="Clusters"
            collapsed={sidebarCollapsed}
          />
        </NavGroup>
      </nav>

      <FooterBlock collapsed={sidebarCollapsed} />
    </div>
  );
}

function NavGroup({
  label,
  collapsed,
  children,
}: {
  label: string;
  collapsed: boolean;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <div
        className={cn(
          "section-label whitespace-nowrap px-2 text-white/40 transition-opacity duration-200 ease-out",
          collapsed ? "opacity-0" : "opacity-100",
        )}
        aria-hidden={collapsed}
      >
        {label}
      </div>
      <div className="flex flex-col gap-0.5">{children}</div>
    </div>
  );
}

function NavItem({
  to,
  icon,
  label,
  collapsed,
}: {
  to: string;
  icon: ReactNode;
  label: string;
  collapsed: boolean;
}) {
  return (
    <NavLink
      to={to}
      title={collapsed ? label : undefined}
      className={({ isActive }) =>
        cn(
          "group flex h-9 items-center rounded-md px-2 text-sm transition-colors",
          isActive
            ? "bg-white/10 text-white"
            : "text-white/70 hover:bg-white/5 hover:text-white",
        )
      }
    >
      {({ isActive }) => (
        <>
          <span
            className={cn(
              "flex h-5 w-5 shrink-0 items-center justify-center transition-colors",
              isActive ? "text-status-fix" : "text-white/60 group-hover:text-white/90",
            )}
          >
            {icon}
          </span>
          <span
            className={cn(
              "overflow-hidden whitespace-nowrap font-medium",
              COLLAPSE_TRANSITION,
              collapsed ? "ml-0 max-w-0 opacity-0" : "ml-3 max-w-40 opacity-100",
            )}
          >
            {label}
          </span>
        </>
      )}
    </NavLink>
  );
}

function FooterBlock({ collapsed }: { collapsed: boolean }) {
  return (
    <div
      className={cn(
        "mt-auto overflow-hidden border-t border-sidebar-border text-xs text-white/50",
        COLLAPSE_TRANSITION,
        collapsed ? "max-h-0 opacity-0 py-0" : "max-h-16 opacity-100 py-4",
      )}
    >
      <div className="px-5 whitespace-nowrap">
        <div className="font-medium text-white/70">Local instance</div>
        <div className="entity-id mt-0.5">localhost:8765</div>
      </div>
    </div>
  );
}
