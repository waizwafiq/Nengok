import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ClusterDetailPage } from "../ClusterDetailPage";
import { renderWithProviders } from "../../test/renderWithProviders";
import * as clustersApi from "../../api/clusters";
import * as artifactsApi from "../../api/artifacts";
import * as approvalsApi from "../../api/approvals";
import * as experimentsApi from "../../api/experiments";
import type { Cluster } from "../../types/cluster";
import type { ArtifactBundle } from "../../types/artifact";

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

function buildArtifacts(overrides: Partial<ArtifactBundle> = {}): ArtifactBundle {
  return {
    cluster_id: "c-1",
    prompt: "# Proposed prompt\n\nUse a typed departure_time field.",
    regression: '[{"case_id":"r-1"}]',
    rca: "# Root-cause analysis\n\nSchema drift detected in flights.search.",
    ...overrides,
  };
}

function mockExperiments() {
  vi.spyOn(experimentsApi, "fetchLatestExperiment").mockResolvedValue(null);
}

describe("ClusterDetailPage", () => {
  it("renders cluster name, RCA artifact, and approval buttons once data loads", async () => {
    vi.spyOn(clustersApi, "fetchCluster").mockResolvedValue(buildCluster());
    vi.spyOn(artifactsApi, "fetchArtifacts").mockResolvedValue(buildArtifacts());
    mockExperiments();

    renderWithProviders(<ClusterDetailPage />, {
      initialPath: "/clusters/c-1",
      routePath: "/clusters/:clusterId",
    });

    expect(await screen.findByText("schema-drift-on-flights")).toBeInTheDocument();
    expect(await screen.findByText(/Schema drift detected/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeInTheDocument();
  });

  it("submits an approval decision when the Approve button is clicked", async () => {
    vi.spyOn(clustersApi, "fetchCluster").mockResolvedValue(buildCluster());
    vi.spyOn(artifactsApi, "fetchArtifacts").mockResolvedValue(buildArtifacts());
    mockExperiments();
    const submit = vi.spyOn(approvalsApi, "submitApproval").mockResolvedValue({
      approval_id: "a-1",
      cluster_id: "c-1",
      status: "approved",
    });

    renderWithProviders(<ClusterDetailPage />, {
      initialPath: "/clusters/c-1",
      routePath: "/clusters/:clusterId",
    });

    const approve = await screen.findByRole("button", { name: "Approve" });
    await userEvent.click(approve);

    await waitFor(() => {
      expect(submit).toHaveBeenCalledWith("c-1", "approved");
    });
  });

  it("falls back to a 'No RCA artifact yet' message when artifacts are missing", async () => {
    vi.spyOn(clustersApi, "fetchCluster").mockResolvedValue(buildCluster());
    vi.spyOn(artifactsApi, "fetchArtifacts").mockResolvedValue(
      buildArtifacts({ rca: null, prompt: null }),
    );
    mockExperiments();

    renderWithProviders(<ClusterDetailPage />, {
      initialPath: "/clusters/c-1",
      routePath: "/clusters/:clusterId",
    });

    expect(await screen.findByText("No RCA artifact yet.")).toBeInTheDocument();
  });

  it("renders an error card when the cluster fetch fails", async () => {
    vi.spyOn(clustersApi, "fetchCluster").mockRejectedValue(new Error("404"));
    vi.spyOn(artifactsApi, "fetchArtifacts").mockResolvedValue(buildArtifacts());
    mockExperiments();

    renderWithProviders(<ClusterDetailPage />, {
      initialPath: "/clusters/c-1",
      routePath: "/clusters/:clusterId",
    });

    expect(
      await screen.findByText(/Could not load this cluster/),
    ).toBeInTheDocument();
  });
});
