import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApprovalHistory } from "../ApprovalHistory";
import { renderWithProviders } from "../../../test/renderWithProviders";
import * as approvalsApi from "../../../api/approvals";
import type { ApprovalRecord } from "../../../types/approval";

afterEach(() => {
  vi.restoreAllMocks();
});

function approval(overrides: Partial<ApprovalRecord> = {}): ApprovalRecord {
  return {
    approval_id: "a-1",
    cluster_id: "c-1",
    decision: "approved",
    reviewer: "alice",
    reason: null,
    created_at: "2026-05-25T12:00:00Z",
    ...overrides,
  };
}

describe("ApprovalHistory", () => {
  it("renders reviewer, badge, and timestamp for each row", async () => {
    vi.spyOn(approvalsApi, "fetchClusterApprovals").mockResolvedValue([
      approval({ approval_id: "a-1", reviewer: "alice", reason: "Looks fine." }),
      approval({
        approval_id: "a-2",
        decision: "rejected",
        reviewer: "bob",
        reason: null,
      }),
    ]);

    renderWithProviders(<ApprovalHistory clusterId="c-1" />);

    expect(await screen.findByText("alice")).toBeInTheDocument();
    expect(screen.getByText("Looks fine.")).toBeInTheDocument();
    expect(screen.getByText("bob")).toBeInTheDocument();
    expect(screen.getByText("No reason provided.")).toBeInTheDocument();
    expect(screen.getByText("Rejected")).toBeInTheDocument();
  });

  it("collapses a long reason behind a Show more toggle", async () => {
    const longReason = "x".repeat(400);
    vi.spyOn(approvalsApi, "fetchClusterApprovals").mockResolvedValue([
      approval({ reason: longReason }),
    ]);

    renderWithProviders(<ApprovalHistory clusterId="c-1" />);

    const toggle = await screen.findByRole("button", { name: "Show more" });
    await userEvent.click(toggle);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Show less" })).toBeInTheDocument();
    });
  });

  it("renders an empty state when no approvals have been recorded", async () => {
    vi.spyOn(approvalsApi, "fetchClusterApprovals").mockResolvedValue([]);

    renderWithProviders(<ApprovalHistory clusterId="c-1" />);

    expect(
      await screen.findByText(/No approval decisions have been recorded/),
    ).toBeInTheDocument();
  });
});
