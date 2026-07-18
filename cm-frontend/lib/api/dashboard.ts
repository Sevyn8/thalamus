import { apiFetch } from "./client";
import type {
  FleetStatsResponse,
  GovernanceStatsResponse,
} from "@/types/api";

// Phase 5h.4 (2026-05-23): `recentActivity` removed — the dashboard's
// activity panel now consumes /api/v1/audit/activities directly via
// `useAuditActivities` (the Step 6.16.3 endpoint). The pre-5h.1
// /api/v1/dashboard/recent-activity placeholder never shipped.

export const dashboardApi = {
  fleetStats: () =>
    apiFetch<FleetStatsResponse>(`/api/v1/dashboard/fleet-stats`),
  governanceStats: () =>
    apiFetch<GovernanceStatsResponse>(`/api/v1/dashboard/governance-stats`),
};
