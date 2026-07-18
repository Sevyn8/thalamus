import { disApiFetch, disQs } from "./client";
import type { ListResponse } from "@/lib/api/types";
import type {
  CreateTemplateInput,
  Template,
  TemplateListParams,
  UpdateTemplateInput,
} from "@/types/dis";

// Phase 5c.5a: read-only templates API.
// Phase 5e.6: create + update mutations land alongside
// AddSuperTemplateWizard + the light edit form.

export const templatesApi = {
  list: (params?: TemplateListParams) =>
    disApiFetch<ListResponse<Template>>(
      `/api/v1/dis/templates${disQs(params as Record<string, unknown> | undefined)}`,
    ),

  get: (id: string) => disApiFetch<Template>(`/api/v1/dis/templates/${id}`),

  create: (input: CreateTemplateInput) =>
    disApiFetch<Template>(`/api/v1/dis/templates`, {
      method: "POST",
      body: JSON.stringify(input),
      headers: { "Idempotency-Key": crypto.randomUUID() },
    }),

  update: (id: string, input: UpdateTemplateInput) =>
    disApiFetch<Template>(`/api/v1/dis/templates/${id}`, {
      method: "PATCH",
      body: JSON.stringify(input),
      headers: { "Idempotency-Key": crypto.randomUUID() },
    }),
};
