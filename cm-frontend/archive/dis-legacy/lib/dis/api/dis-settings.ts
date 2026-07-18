import { disApiFetch } from "./client";
import type { DisTenantSettings, UpdateDisSettingsInput } from "@/types/dis";

export const disSettingsApi = {
  get: () => disApiFetch<DisTenantSettings>(`/api/v1/dis/tenant-settings`),

  update: (input: UpdateDisSettingsInput) =>
    disApiFetch<DisTenantSettings>(`/api/v1/dis/tenant-settings`, {
      method: "PATCH",
      body: JSON.stringify(input),
      headers: {
        "Idempotency-Key": crypto.randomUUID(),
      },
    }),
};
