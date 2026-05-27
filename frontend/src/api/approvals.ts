import { apiClient } from "./client";
import type { ApprovalDecision, ApprovalRecord, ApprovalResult } from "../types/approval";

export interface ApprovalSubmission {
  decision: ApprovalDecision;
  reviewer?: string | null;
  reason?: string | null;
}

export async function submitApproval(
  clusterId: string,
  submission: ApprovalSubmission,
): Promise<ApprovalResult> {
  const response = await apiClient.post<ApprovalResult>(
    `/clusters/${encodeURIComponent(clusterId)}/approvals`,
    {
      decision: submission.decision,
      reviewer: submission.reviewer ?? null,
      reason: submission.reason ?? null,
    },
  );
  return response.data;
}

export async function fetchClusterApprovals(clusterId: string): Promise<ApprovalRecord[]> {
  const response = await apiClient.get<ApprovalRecord[]>(
    `/clusters/${encodeURIComponent(clusterId)}/approvals`,
  );
  return response.data;
}

export async function fetchApprovalFeed(params?: {
  limit?: number;
  before?: string;
}): Promise<ApprovalRecord[]> {
  const response = await apiClient.get<ApprovalRecord[]>("/approvals", { params });
  return response.data;
}
