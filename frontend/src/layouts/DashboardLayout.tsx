import { Outlet } from "react-router-dom";
import { Header } from "../components/layout/Header";
import { TopBar } from "../components/layout/TopBar";

export function DashboardLayout() {
  return (
    <div className="relative flex h-screen overflow-hidden bg-sidebar text-sm">
      <aside className="flex w-60 shrink-0 flex-col bg-sidebar text-sidebar-foreground">
        <Header />
      </aside>

      <main className="flex h-full min-w-0 flex-1 flex-col overflow-hidden">
        <TopBar />
        <div className="flex-1 overflow-y-auto rounded-tl-3xl border-t border-l border-border bg-background animate-in fade-in duration-300">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
