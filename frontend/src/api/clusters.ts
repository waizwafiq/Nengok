import { apiClient } from "./client";
import type { Cluster, ClusterLink, ClusterStatus } from "../types/cluster";

export async function fetchClusters(status?: ClusterStatus, project?: string): Promise<Cluster[]> {
  const params: Record<string, string> = {};
  if (status) {
    params.status = status;
  }
  if (project) {
    params.project = project;
  }
  const response = await apiClient.get<Cluster[]>("/clusters", {
    params: Object.keys(params).length > 0 ? params : undefined,
  });
  return response.data;
}

export async function fetchCluster(clusterId: string): Promise<Cluster> {
  const response = await apiClient.get<Cluster>(`/clusters/${clusterId}`);
  return response.data;
}

export async function fetchClusterLinks(clusterId: string): Promise<ClusterLink[]> {
  const response = await apiClient.get<ClusterLink[]>(`/clusters/${clusterId}/links`);
  return response.data;
}
