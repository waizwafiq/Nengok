export type ApprovalDecision = "approved" | "rejected" | "dismissed" | "escalated";

export type FeedbackTag = "duplicate_cluster" | "mixed_root_causes" | "not_a_failure";

export interface ApprovalResult {
  approval_id: string;
  cluster_id: string;
  status: string;
}

export interface ApprovalRecord {
  approval_id: string;
  cluster_id: string;
  decision: ApprovalDecision;
  reviewer: string | null;
  reason: string | null;
  created_at: string;
}
