export type ApprovalDecision = "approved" | "rejected" | "dismissed" | "escalated";

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
