import { apiClient } from "./client";

export interface ClusteringAdvice {
  advice_id: string;
  project: string | null;
  status: "proposed" | "active" | "retired";
  prompt_amendment: string;
  metrics_json: string | null;
  created_at: string;
  decided_by: string | null;
  decided_at: string | null;
}

export async function fetchAdvice(status?: string): Promise<ClusteringAdvice[]> {
  const response = await apiClient.get<ClusteringAdvice[]>("/advice", {
    params: status ? { status } : undefined,
  });
  return response.data;
}

export async function activateAdvice(adviceId: string): Promise<ClusteringAdvice> {
  const response = await apiClient.post<ClusteringAdvice>(
    `/advice/${encodeURIComponent(adviceId)}/activate`,
    {},
  );
  return response.data;
}
