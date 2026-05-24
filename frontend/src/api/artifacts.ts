import { apiClient } from "./client";
import type { ArtifactBundle } from "../types/artifact";

export async function fetchArtifacts(clusterId: string): Promise<ArtifactBundle> {
  const response = await apiClient.get<ArtifactBundle>(`/artifacts/${clusterId}`);
  return response.data;
}
