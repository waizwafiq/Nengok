import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OverviewPage } from "../OverviewPage";
import { renderWithProviders } from "../../test/renderWithProviders";
import * as dashboardApi from "../../api/dashboard";
import * as clustersApi from "../../api/clusters";
import type { DashboardOverview } from "../../types/dashboard";
import type { Cluster } from "../../types/cluster";

afterEach(() => {
  vi.restoreAllMocks();
});

function buildOverview(overrides: Partial<DashboardOverview> = {}): DashboardOverview {
  return {
    cluster_counts: {
      open: 2,
      diagnosed: 3,
      fix_proposed: 1,
      approved: 4,
      rejected: 0,
      dismissed: 0,
      escalated: 1,
    },
    mttd_seconds: 90,
    mttr_seconds: 1800,
    close_rate: 0.5,
    regression_test_count: 12,
    fix_pass_rate_30d: 0.85,
    gemini_tokens_used_30d: 8_000,
    gemini_dollars_used_30d: 0.23,
    gemini_spend_sparkline_30d: [
      { day: "2026-05-25", tokens: 4_000, dollars: 0.12 },
      { day: "2026-05-26", tokens: 4_000, dollars: 0.11 },
    ],
    ...overrides,
  };
}

function buildCluster(overrides: Partial<Cluster> = {}): Cluster {
  return {
    cluster_id: "c-1",
    name: "schema-drift-on-flights",
    description: "d",
    status: "open",
    hypothesis_json: null,
    member_spans_json: "[]",
    created_at: "2026-05-25T00:00:00Z",
    updated_at: "2026-05-25T00:00:00Z",
    ...overrides,
  };
}

describe("OverviewPage", () => {
  it("renders the cluster counts and Gemini spend once data loads", async () => {
    vi.spyOn(dashboardApi, "fetchDashboardOverview").mockResolvedValue(buildOverview());
    vi.spyOn(clustersApi, "fetchClusters").mockResolvedValue([buildCluster()]);

    renderWithProviders(<OverviewPage />);

    expect(await screen.findByText("Portfolio overview")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText("Open clusters")).toBeInTheDocument();
    });
    expect(screen.getByText("Fix proposed")).toBeInTheDocument();
    expect(screen.getByText("$0.23")).toBeInTheDocument();
    expect(screen.getByText(/8\.0k tokens/)).toBeInTheDocument();
  });

  it("shows the empty-state banner when there are no clusters", async () => {
    vi.spyOn(dashboardApi, "fetchDashboardOverview").mockResolvedValue(
      buildOverview({
        cluster_counts: {
          open: 0,
          diagnosed: 0,
          fix_proposed: 0,
          approved: 0,
          rejected: 0,
          dismissed: 0,
          escalated: 0,
        },
      }),
    );
    vi.spyOn(clustersApi, "fetchClusters").mockResolvedValue([]);

    renderWithProviders(<OverviewPage />);

    expect(await screen.findByText(/No clusters yet/)).toBeInTheDocument();
    expect(screen.getByText("Open clusters view")).toBeInTheDocument();
  });

  it("renders an error card when the overview request fails", async () => {
    vi.spyOn(dashboardApi, "fetchDashboardOverview").mockRejectedValue(new Error("boom"));
    vi.spyOn(clustersApi, "fetchClusters").mockResolvedValue([]);

    renderWithProviders(<OverviewPage />);

    expect(
      await screen.findByText(/Could not load dashboard metrics/),
    ).toBeInTheDocument();
  });

  it("surfaces the recent cycle outcomes and per-cycle spend", async () => {
    vi.spyOn(dashboardApi, "fetchDashboardOverview").mockResolvedValue(
      buildOverview({
        recent_cycles: [
          {
            cycle_id: "c-2",
            started_at: "2026-05-26T15:00:00Z",
            ended_at: "2026-05-26T15:10:00Z",
            status: "ok",
            clusters_processed: 3,
            clusters_discovered: 3,
            gemini_tokens: 5_000,
            gemini_dollars: 0.14,
            error_message: null,
          },
          {
            cycle_id: "c-1",
            started_at: "2026-05-25T15:00:00Z",
            ended_at: "2026-05-25T15:08:00Z",
            status: "over_budget",
            clusters_processed: 2,
            clusters_discovered: 4,
            gemini_tokens: 8_000,
            gemini_dollars: 0.22,
            error_message: null,
          },
        ],
        recent_cycle_status_counts: { ok: 1, over_budget: 1 },
      }),
    );
    vi.spyOn(clustersApi, "fetchClusters").mockResolvedValue([buildCluster()]);

    renderWithProviders(<OverviewPage />);

    expect(await screen.findByText(/Cost of last 2 cycles/)).toBeInTheDocument();
    expect(screen.getByText(/Cycle outcomes \(last 2\)/)).toBeInTheDocument();
    expect(screen.getByText("Over budget")).toBeInTheDocument();
    expect(screen.getByText("$0.14")).toBeInTheDocument();
  });

  it("formats null MTTD/MTTR as an em-dash placeholder", async () => {
    vi.spyOn(dashboardApi, "fetchDashboardOverview").mockResolvedValue(
      buildOverview({ mttd_seconds: null, mttr_seconds: null, fix_pass_rate_30d: null }),
    );
    vi.spyOn(clustersApi, "fetchClusters").mockResolvedValue([buildCluster()]);

    renderWithProviders(<OverviewPage />);

    await waitFor(() => {
      expect(screen.getByText("Mean time to detect")).toBeInTheDocument();
    });
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(2);
  });
});
