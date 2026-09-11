import { apiFetch, qs } from "./client";
import type {
  Store,
  StoreDetail,
  StoreListResponse,
  StoreStatus,
} from "@/types/api";
import type { components } from "@/types/openapi-generated";

export type StoreCreatePayload = components["schemas"]["StoreCreateRequest"];
export type StorePatchPayload = components["schemas"]["StorePatchRequest"];

export type StoreListParams = {
  status?: StoreStatus;
  tenant_id?: string;
  search?: string;
  offset?: number;
  limit?: number;
};

// All endpoints hit the backend via apiFetch per lib/api/client.ts.
// Permission tuple ADMIN.STORES.CONFIGURE.TENANT gates every write.
export const storesApi = {
  list: (params?: StoreListParams) =>
    apiFetch<StoreListResponse>(
      `/api/v1/stores${qs(params as Record<string, unknown> | undefined)}`,
    ),

  get: (id: string) => apiFetch<StoreDetail>(`/api/v1/stores/${id}`),

  create: (input: StoreCreatePayload) =>
    apiFetch<StoreDetail>(`/api/v1/stores`, {
      method: "POST",
      body: JSON.stringify(input),
      headers: {
        "Idempotency-Key": crypto.randomUUID(),
      },
    }),

  patch: (id: string, input: StorePatchPayload) =>
    apiFetch<StoreDetail>(`/api/v1/stores/${id}`, {
      method: "PATCH",
      body: JSON.stringify(input),
      headers: {
        "Idempotency-Key": crypto.randomUUID(),
      },
    }),

  setStatus: (id: string, target_status: StoreStatus, reason?: string) =>
    apiFetch<StoreDetail>(`/api/v1/stores/${id}/set-status`, {
      method: "POST",
      body: JSON.stringify({
        target_status,
        ...(reason !== undefined ? { reason } : {}),
      }),
      headers: {
        "Idempotency-Key": crypto.randomUUID(),
      },
    }),
};

// Re-export for consumers that need to import the Store row type
// alongside the api client.
export type { Store };
