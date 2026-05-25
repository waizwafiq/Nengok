import { apiClient } from "./client";
import type { ExperimentSummary } from "../types/experiment";

export async function fetchLatestExperiment(clusterId: string): Promise<ExperimentSummary | null> {
  try {
    const response = await apiClient.get<ExperimentSummary>(`/experiments/${clusterId}/latest`);
    return response.data;
  } catch (error: unknown) {
    if (
      typeof error === "object" &&
      error !== null &&
      "response" in error &&
      (error as { response?: { status?: number } }).response?.status === 404
    ) {
      return null;
    }
    throw error;
  }
}
