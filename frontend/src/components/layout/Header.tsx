import { NavLink } from "react-router-dom";
import { Activity, LayoutDashboard } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "../../lib/cn";
import { useLayout } from "./useLayout";
import logoFull from "../../assets/nengok-logo.png";
import logoMark from "../../assets/nengok-logoonly.png";

/**
 * Owned by the layout shell so individual pages do not redraw the nav
 * on route changes. Add new top-level destinations here, not in
 * DashboardLayout.
 */
export function Header() {
  const { sidebarCollapsed } = useLayout();

  return (
    <>
      <div
        className={cn(
          "flex h-14 items-center transition-[padding] duration-200",
          sidebarCollapsed ? "justify-center px-3" : "px-5",
        )}
      >
        {sidebarCollapsed ? (
          <img src={logoMark} alt="Nengok" className="h-7 w-7" />
        ) : (
          <img src={logoFull} alt="Nengok" className="h-7" />
        )}
      </div>

      <nav
        className={cn(
          "flex flex-col gap-4 pt-4",
          sidebarCollapsed ? "px-2" : "px-3",
        )}
        aria-label="Primary"
      >
        <NavGroup label="Workspace" collapsed={sidebarCollapsed}>
          <NavItem
            to="/overview"
            icon={<LayoutDashboard className="h-4 w-4" />}
            label="Overview"
            hint="Snapshot of every cluster"
            collapsed={sidebarCollapsed}
          />
          <NavItem
            to="/clusters"
            icon={<Activity className="h-4 w-4" />}
            label="Clusters"
            hint="Failure groups and fixes"
            collapsed={sidebarCollapsed}
          />
        </NavGroup>
      </nav>

      {sidebarCollapsed ? null : (
        <div className="mt-auto px-5 py-4 border-t border-sidebar-border text-xs text-white/50">
          <div className="font-medium text-white/70">Local instance</div>
          <div className="entity-id mt-0.5">localhost:8765</div>
        </div>
      )}
    </>
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
      {collapsed ? null : <div className="section-label px-2 text-white/40">{label}</div>}
      <div className="flex flex-col gap-0.5">{children}</div>
    </div>
  );
}

function NavItem({
  to,
  icon,
  label,
  hint,
  collapsed,
}: {
  to: string;
  icon: ReactNode;
  label: string;
  hint: string;
  collapsed: boolean;
}) {
  return (
    <NavLink
      to={to}
      title={collapsed ? label : undefined}
      className={({ isActive }) =>
        cn(
          "group flex items-center rounded-md text-sm transition-colors",
          collapsed ? "h-9 w-9 justify-center self-center" : "items-start gap-3 px-2 py-2",
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
              "transition-colors",
              collapsed ? "" : "mt-0.5",
              isActive ? "text-status-fix" : "text-white/50 group-hover:text-white/80",
            )}
          >
            {icon}
          </span>
          {collapsed ? null : (
            <span className="flex min-w-0 flex-col leading-tight">
              <span className="font-medium">{label}</span>
              <span className="text-[11px] text-white/40">{hint}</span>
            </span>
          )}
        </>
      )}
    </NavLink>
  );
}
