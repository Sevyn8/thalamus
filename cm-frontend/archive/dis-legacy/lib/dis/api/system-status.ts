import { disApiFetch } from "./client";
import type { ServiceStatusResponse } from "@/types/dis";

// Phase 5c.8f2: read-only system status. Single endpoint, single
// shape; mirrors the static-list surfaces in DIS (no scope, no
// query params).

export const systemStatusApi = {
  read: () => disApiFetch<ServiceStatusResponse>(`/api/v1/dis/system-status`),
};
