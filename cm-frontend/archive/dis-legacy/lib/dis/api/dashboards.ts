import { disApiFetch } from "./client";
import type { DisDashboardResponse } from "@/types/dis";

// Phase 5e.10b: operational dashboard read endpoint. No window
// param (KPIs are inherently fixed-window per type). Server-side
// persona gating: PLATFORM reads any tenant_id; TENANT reads own.

export const dashboardsApi = {
  tenant: (tenantId: string) =>
    disApiFetch<DisDashboardResponse>(
      `/api/v1/dis/dashboards/${encodeURIComponent(tenantId)}`,
    ),
};
