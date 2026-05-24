export type ClusterStatus =
  | "open"
  | "diagnosed"
  | "fix_proposed"
  | "approved"
  | "rejected"
  | "dismissed"
  | "escalated";

export interface RootCauseHypothesis {
  summary: string;
  expected_behavior: string;
  actual_behavior: string;
  likely_cause: string;
  implicated_tools: string[];
}

export interface Cluster {
  cluster_id: string;
  name: string;
  description: string;
  status: ClusterStatus;
  hypothesis_json: string | null;
  member_spans_json: string;
  created_at: string;
  updated_at: string;
}
