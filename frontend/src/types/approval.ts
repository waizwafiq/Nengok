export type ApprovalDecision = "approved" | "rejected" | "dismissed";

export interface ApprovalResult {
  approval_id: string;
  cluster_id: string;
  status: string;
}
