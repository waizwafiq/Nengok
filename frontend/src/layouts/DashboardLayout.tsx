import { NavLink, Outlet } from "react-router-dom";
import { Activity, LayoutDashboard, ScanEye } from "lucide-react";

export function DashboardLayout() {
  return (
    <div className="min-h-screen flex">
      <aside className="w-60 border-r border-neutral-200 bg-white px-4 py-6 flex flex-col gap-1">
        <div className="px-2 pb-6">
          <div className="flex items-center gap-2">
            <ScanEye className="w-6 h-6 text-brand-primary" />
            <span className="font-semibold text-lg">Nengok</span>
          </div>
          <p className="text-xs text-neutral-500 mt-1">
            Watches your agents. Fixes what's quietly wrong.
          </p>
        </div>

        <NavItem to="/overview" icon={<LayoutDashboard className="w-4 h-4" />} label="Overview" />
        <NavItem to="/clusters" icon={<Activity className="w-4 h-4" />} label="Clusters" />
      </aside>

      <main className="flex-1 p-8 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}

function NavItem({ to, icon, label }: { to: string; icon: React.ReactNode; label: string }) {
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
