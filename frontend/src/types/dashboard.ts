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

export type CycleStatus = "ok" | "over_budget" | "failed" | "circuit_broken" | "skipped_by_triage";

export interface RecentCycle {
  cycle_id: string;
  started_at: string;
  ended_at: string;
  status: CycleStatus;
  clusters_processed: number;
  clusters_discovered: number;
  gemini_tokens: number;
  gemini_dollars: number;
  error_message: string | null;
}

export type RecentCycleStatusCounts = Partial<Record<CycleStatus, number>>;

export interface DuplicateRatePoint {
  day: string;
  rate: number;
}

export interface ClusteringQuality {
  duplicate_rate_trend: DuplicateRatePoint[];
  latest_golden_f1: number | null;
}

export interface DashboardOverview {
  cluster_counts: ClusterCounts;
  mttd_seconds: number | null;
  mttr_seconds: number | null;
  close_rate: number;
  regression_test_count: number;
  fix_pass_rate_30d: number | null;
  gemini_tokens_used_30d?: number;
  gemini_dollars_used_30d?: number;
  gemini_spend_sparkline_30d?: GeminiSpendPoint[];
  recent_cycles?: RecentCycle[];
  recent_cycle_status_counts?: RecentCycleStatusCounts;
  clustering_quality?: ClusteringQuality;
}
