import { disApiFetch } from "./client";
import type {
  CostFleetResponse,
  CostFleetRow,
  SetBudgetInput,
} from "@/types/dis";

// Phase 5c.8e2: Cost fleet view + budget setter (PLATFORM-only).

export const costApi = {
  fleet: () => disApiFetch<CostFleetResponse>(`/api/v1/dis/admin/cost`),

  setBudget: (tenantId: string, input: SetBudgetInput) =>
    disApiFetch<CostFleetRow>(
      `/api/v1/dis/admin/cost/${encodeURIComponent(tenantId)}/budget`,
      { method: "PUT", body: JSON.stringify(input) },
    ),
};
