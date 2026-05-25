import { NavLink } from "react-router-dom";
import { Activity, LayoutDashboard, ScanEye } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

/**
 * Owned by the layout shell so individual pages do not redraw the nav
 * on route changes. Add new top-level destinations here, not in
 * DashboardLayout.
 */
export function Header() {
  return (
    <>
      <div className="flex h-14 items-center gap-2.5 px-5">
        <div className="flex h-8 w-8 items-center justify-center rounded-md bg-status-fix/15 text-status-fix">
          <ScanEye className="h-4.5 w-4.5" aria-hidden="true" />
        </div>
        <div className="leading-tight">
          <div className="text-sm font-semibold tracking-tight text-white">Nengok</div>
          <div className="entity-id text-white/50">Operations console</div>
        </div>
      </div>

      <nav className="flex flex-col gap-4 px-3 pt-4" aria-label="Primary">
        <NavGroup label="Workspace">
          <NavItem
            to="/overview"
            icon={<LayoutDashboard className="h-4 w-4" />}
            label="Overview"
            hint="Snapshot of every cluster"
          />
          <NavItem
            to="/clusters"
            icon={<Activity className="h-4 w-4" />}
            label="Clusters"
            hint="Failure groups and fixes"
          />
        </NavGroup>
      </nav>

      <div className="mt-auto px-5 py-4 border-t border-sidebar-border text-xs text-white/50">
        <div className="font-medium text-white/70">Local instance</div>
        <div className="entity-id mt-0.5">localhost:8765</div>
      </div>
    </>
  );
}

function NavGroup({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <div className="section-label px-2 text-white/40">{label}</div>
      <div className="flex flex-col gap-0.5">{children}</div>
    </div>
  );
}

function NavItem({
  to,
  icon,
  label,
  hint,
}: {
  to: string;
  icon: ReactNode;
  label: string;
  hint: string;
}) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cn(
          "group flex items-start gap-3 rounded-md px-2 py-2 text-sm transition-colors",
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
              "mt-0.5 transition-colors",
              isActive ? "text-status-fix" : "text-white/50 group-hover:text-white/80",
            )}
          >
            {icon}
          </span>
          <span className="flex min-w-0 flex-col leading-tight">
            <span className="font-medium">{label}</span>
            <span className="text-[11px] text-white/40">{hint}</span>
          </span>
        </>
      )}
    </NavLink>
  );
}
