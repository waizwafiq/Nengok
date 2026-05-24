import { apiClient } from "./client";
import type { Cluster, ClusterStatus } from "../types/cluster";

export async function fetchClusters(status?: ClusterStatus): Promise<Cluster[]> {
  const response = await apiClient.get<Cluster[]>("/clusters", {
    params: status ? { status } : undefined,
  });
  return response.data;
}

export async function fetchCluster(clusterId: string): Promise<Cluster> {
  const response = await apiClient.get<Cluster>(`/clusters/${clusterId}`);
  return response.data;
}
