import { Outlet } from "react-router-dom";
import { Header } from "../components/layout/Header";

export function DashboardLayout() {
  return (
    <div className="min-h-screen flex">
      <aside className="w-60 border-r border-neutral-200 bg-white px-4 py-6 flex flex-col gap-1">
        <Header />
      </aside>

      <main className="flex-1 p-8 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}
