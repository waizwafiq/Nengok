import { apiClient } from "./client";
import type { ApprovalDecision, ApprovalResult } from "../types/approval";

export async function submitApproval(
  clusterId: string,
  decision: ApprovalDecision,
  notes?: string
): Promise<ApprovalResult> {
  const response = await apiClient.post<ApprovalResult>("/approvals", {
    cluster_id: clusterId,
    decision,
    notes,
  });
  return response.data;
}
