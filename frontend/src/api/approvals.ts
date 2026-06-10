import { apiClient } from "./client";
import type {
  ApprovalDecision,
  ApprovalRecord,
  ApprovalResult,
  FeedbackTag,
} from "../types/approval";

export interface ApprovalSubmission {
  decision: ApprovalDecision;
  reviewer?: string | null;
  reason?: string | null;
  feedback_tag?: FeedbackTag | null;
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
      feedback_tag: submission.feedback_tag ?? null,
    },
  );
  return response.data;
}

export interface MergeWrongResult {
  feedback_id: string;
  cluster_id: string;
  detached_span_ids: string[];
  detached_count: number;
}

export async function flagMergeWrong(
  clusterId: string,
  spanIds: string[],
  reason?: string | null,
): Promise<MergeWrongResult> {
  const response = await apiClient.post<MergeWrongResult>(
    `/clusters/${encodeURIComponent(clusterId)}/feedback/merge-wrong`,
    { span_ids: spanIds, reason: reason ?? null },
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
