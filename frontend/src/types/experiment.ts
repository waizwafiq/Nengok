export interface ExperimentCase {
  case_id?: string;
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
  expected?: Record<string, unknown>;
  passed?: boolean;
  evaluators?: Record<string, boolean | number | string>;
  [key: string]: unknown;
}

export interface ExperimentSummary {
  experiment_id: string | null;
  cluster_id: string;
  experiment_name: string;
  dataset_name: string;
  baseline_pass_rate: number;
  fix_pass_rate: number;
  golden_baseline_pass_rate: number;
  golden_fix_pass_rate: number;
  per_case: ExperimentCase[];
  created_at: string;
}
