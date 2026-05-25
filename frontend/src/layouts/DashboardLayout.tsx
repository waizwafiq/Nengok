import { Outlet } from "react-router-dom";
import { Header } from "../components/layout/Header";
import { TopBar } from "../components/layout/TopBar";
import { LayoutProvider } from "../components/layout/LayoutContext";
import { useLayout } from "../components/layout/useLayout";
import { cn } from "../lib/cn";

export function DashboardLayout() {
  return (
    <LayoutProvider>
      <Shell />
    </LayoutProvider>
  );
}

function Shell() {
  const { sidebarCollapsed } = useLayout();
  return (
    <div className="relative flex h-screen overflow-hidden bg-sidebar text-sm">
      <aside
        className={cn(
          "flex shrink-0 flex-col bg-sidebar text-sidebar-foreground transition-[width] duration-200 ease-out",
          sidebarCollapsed ? "w-16" : "w-60",
        )}
      >
        <Header />
      </aside>

      <main className="flex h-full min-w-0 flex-1 flex-col overflow-hidden">
        <TopBar />
        <div className="flex-1 overflow-y-auto rounded-tl-xl border-t border-l border-border bg-background animate-in fade-in duration-300">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
