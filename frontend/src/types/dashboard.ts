export interface ClusterCounts {
  open: number;
  diagnosed: number;
  fix_proposed: number;
  approved: number;
  rejected: number;
  dismissed: number;
  escalated: number;
}

export interface GeminiSpendPoint {
  day: string;
  tokens: number;
  dollars: number;
}

export interface DashboardOverview {
  cluster_counts: ClusterCounts;
  mttd_seconds: number | null;
  mttr_seconds: number | null;
  close_rate: number;
  regression_test_count: number;
  fix_pass_rate_30d: number | null;
  gemini_tokens_used_30d: number;
  gemini_dollars_used_30d: number;
  gemini_spend_sparkline_30d: GeminiSpendPoint[];
}
