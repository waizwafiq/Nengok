import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  LayoutContext,
  type BreadcrumbItem,
  type LayoutContextValue,
} from "./useLayout";

const COLLAPSE_STORAGE_KEY = "nengok.sidebar.collapsed";

export function LayoutProvider({ children }: { children: ReactNode }) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(() => {
    if (typeof window === "undefined") {
      return false;
    }
    return window.localStorage.getItem(COLLAPSE_STORAGE_KEY) === "1";
  });
  const [breadcrumb, setBreadcrumbState] = useState<BreadcrumbItem[]>([]);

  useEffect(() => {
    window.localStorage.setItem(COLLAPSE_STORAGE_KEY, sidebarCollapsed ? "1" : "0");
  }, [sidebarCollapsed]);

  const toggleSidebar = useCallback(() => {
    setSidebarCollapsed((prev) => !prev);
  }, []);

  const setBreadcrumb = useCallback((items: BreadcrumbItem[]) => {
    setBreadcrumbState(items);
  }, []);

  const value = useMemo<LayoutContextValue>(
    () => ({ sidebarCollapsed, toggleSidebar, breadcrumb, setBreadcrumb }),
    [sidebarCollapsed, toggleSidebar, breadcrumb, setBreadcrumb],
  );

  return <LayoutContext.Provider value={value}>{children}</LayoutContext.Provider>;
}
