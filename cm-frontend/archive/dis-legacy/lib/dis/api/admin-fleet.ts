import { disApiFetch } from "./client";
import type { FleetHealthResponse } from "@/types/dis";

// Phase 5c.8a: read-only fleet-health admin view. MSW-only in v1 —
// no backend equivalent yet. When backend ships matching endpoint
// (future-real), the path stays the same.

export const adminFleetApi = {
  health: () => disApiFetch<FleetHealthResponse>(`/api/v1/dis/admin/fleet`),
};
