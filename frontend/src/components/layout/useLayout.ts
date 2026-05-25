import { createContext, useContext, useEffect } from "react";

export interface BreadcrumbItem {
  label: string;
  href?: string;
}

export interface LayoutContextValue {
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
  breadcrumb: BreadcrumbItem[];
  setBreadcrumb: (items: BreadcrumbItem[]) => void;
}

export const LayoutContext = createContext<LayoutContextValue | null>(null);

export function useLayout(): LayoutContextValue {
  const ctx = useContext(LayoutContext);
  if (!ctx) {
    throw new Error("useLayout must be used inside <LayoutProvider>");
  }
  return ctx;
}

/**
 * Register breadcrumb trail for the topbar from any page.
 *
 * The trail is cleared on unmount so navigating away does not
 * leave stale crumbs in the topbar.
 */
export function useLayoutBreadcrumb(items: BreadcrumbItem[]): void {
  const { setBreadcrumb } = useLayout();
  const serialized = JSON.stringify(items);
  useEffect(() => {
    setBreadcrumb(JSON.parse(serialized) as BreadcrumbItem[]);
    return () => setBreadcrumb([]);
  }, [serialized, setBreadcrumb]);
}
