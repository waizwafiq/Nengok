import { NavLink } from "react-router-dom";
import { Activity, LayoutDashboard, ScanEye } from "lucide-react";
import type { ReactNode } from "react";

/**
 * Owned by the layout shell so individual pages do not redraw the nav
 * on route changes. Add new top-level destinations here, not in
 * DashboardLayout.
 */
export function Header() {
  return (
    <>
      <div className="px-2 pb-6">
        <div className="flex items-center gap-2">
          <ScanEye className="w-6 h-6 text-brand-primary" aria-hidden="true" />
          <span className="font-semibold text-lg">Nengok</span>
        </div>
        <p className="text-xs text-neutral-500 mt-1">
          Watches your agents. Fixes what's quietly wrong.
        </p>
      </div>

      <nav className="flex flex-col gap-1" aria-label="Primary">
        <NavItem to="/overview" icon={<LayoutDashboard className="w-4 h-4" />} label="Overview" />
        <NavItem to="/clusters" icon={<Activity className="w-4 h-4" />} label="Clusters" />
      </nav>
    </>
  );
}

function NavItem({ to, icon, label }: { to: string; icon: ReactNode; label: string }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        [
          "flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors",
          isActive
            ? "bg-brand-primary/10 text-brand-primary font-medium"
            : "text-neutral-600 hover:bg-neutral-100",
        ].join(" ")
      }
    >
      {icon}
      {label}
    </NavLink>
  );
}
