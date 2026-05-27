import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { LayoutProvider } from "../components/layout/LayoutContext";

interface Options {
  initialPath?: string;
  routePath?: string;
}

export function renderWithProviders(ui: ReactElement, options: Options = {}) {
  const { initialPath = "/", routePath = "*" } = options;
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={client}>
      <LayoutProvider>
        <MemoryRouter initialEntries={[initialPath]}>
          <Routes>
            <Route path={routePath} element={ui} />
          </Routes>
        </MemoryRouter>
      </LayoutProvider>
    </QueryClientProvider>,
  );
}
