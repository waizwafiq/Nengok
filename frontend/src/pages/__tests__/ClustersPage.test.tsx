import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ClustersPage } from "../ClustersPage";
import { renderWithProviders } from "../../test/renderWithProviders";
import * as clustersApi from "../../api/clusters";
import type { Cluster, ClusterStatus } from "../../types/cluster";

afterEach(() => {
  vi.restoreAllMocks();
});

function buildCluster(overrides: Partial<Cluster> = {}): Cluster {
  return {
    cluster_id: "c-1",
    name: "schema-drift-on-flights",
    description: "Flights tool returns departure_time as int instead of string.",
    status: "diagnosed",
    hypothesis_json: null,
    member_spans_json: "[]",
    created_at: "2026-05-25T00:00:00Z",
    updated_at: "2026-05-25T00:00:00Z",
    ...overrides,
  };
}

describe("ClustersPage", () => {
  it("renders one card per cluster returned by the API", async () => {
    vi.spyOn(clustersApi, "fetchClusters").mockResolvedValue([
      buildCluster({ cluster_id: "c-1", name: "schema-drift-on-flights" }),
      buildCluster({
        cluster_id: "c-2",
        name: "weather-unit-mismatch",
        status: "approved",
      }),
    ]);

    renderWithProviders(<ClustersPage />);

    expect(await screen.findByText("schema-drift-on-flights")).toBeInTheDocument();
    expect(screen.getByText("weather-unit-mismatch")).toBeInTheDocument();
  });

  it("filters the API request by status when a filter button is pressed", async () => {
    const fetcher = vi
      .spyOn(clustersApi, "fetchClusters")
      .mockResolvedValue([buildCluster()]);

    renderWithProviders(<ClustersPage />);
    await waitFor(() => {
      expect(fetcher).toHaveBeenCalledWith(undefined);
    });

    const approvedFilter = screen.getByRole("button", { name: "Approved" });
    await userEvent.click(approvedFilter);

    await waitFor(() => {
      expect(fetcher).toHaveBeenCalledWith("approved" satisfies ClusterStatus);
    });
  });

  it("shows the empty state when no clusters exist", async () => {
    vi.spyOn(clustersApi, "fetchClusters").mockResolvedValue([]);

    renderWithProviders(<ClustersPage />);

    expect(await screen.findByText(/No clusters yet/)).toBeInTheDocument();
  });

  it("shows the filter-specific empty state when a filter yields nothing", async () => {
    const fetcher = vi
      .spyOn(clustersApi, "fetchClusters")
      .mockResolvedValue([buildCluster()]);

    renderWithProviders(<ClustersPage />);
    await waitFor(() => {
      expect(fetcher).toHaveBeenCalled();
    });

    fetcher.mockResolvedValue([]);
    await userEvent.click(screen.getByRole("button", { name: "Open" }));

    expect(
      await screen.findByText(/No clusters match this filter/),
    ).toBeInTheDocument();
  });

  it("renders an error card when the cluster list fails to load", async () => {
    vi.spyOn(clustersApi, "fetchClusters").mockRejectedValue(new Error("offline"));

    renderWithProviders(<ClustersPage />);

    expect(await screen.findByText(/Could not load clusters/)).toBeInTheDocument();
  });
});
