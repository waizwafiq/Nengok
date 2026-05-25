import { apiClient } from "./client";
import type { DashboardOverview } from "../types/dashboard";

export async function fetchDashboardOverview(): Promise<DashboardOverview> {
  const response = await apiClient.get<DashboardOverview>("/dashboard/overview");
  return response.data;
}
