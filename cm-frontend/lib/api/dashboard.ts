import { apiFetch } from "./client";
import type {
  FleetStatsResponse,
  GovernanceStatsResponse,
} from "@/types/api";

// No recent-activity client here: the dashboard's activity panel
// consumes /api/v1/audit/activities directly via `useAuditActivities`.

export const dashboardApi = {
  fleetStats: () =>
    apiFetch<FleetStatsResponse>(`/api/v1/dashboard/fleet-stats`),
  governanceStats: () =>
    apiFetch<GovernanceStatsResponse>(`/api/v1/dashboard/governance-stats`),
};
