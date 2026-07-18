import { disApiFetch } from "./client";
import type {
  CanonicalSchemaDomain,
  CanonicalSchemaField,
  CanonicalSchemaFieldCreateInput,
  CanonicalSchemaVersionBumpInput,
} from "@/types/dis";

// Phase 5c.1b: read-only list of canonical-schema domains.
// Phase 5c.8b1: PATCH for Anjali field edits (PLATFORM-gated
// server-side).
// Phase 5c.8b2: POST add field + POST bump version. Same PLATFORM
// gate. DELETE (soft deprecate) defers to 5c.8b3.

export type CanonicalSchemaResponse = {
  domains: CanonicalSchemaDomain[];
};

export type CanonicalSchemaFieldUpdateInput = Partial<
  Pick<
    CanonicalSchemaField,
    | "display_name"
    | "description"
    | "type"
    | "required"
    | "nullable"
    | "unique"
    | "business_owner"
    | "example_values"
    | "constraints"
    | "synonyms"
    | "pii"
    // Phase 5d.6: soft-delete uses the same PATCH path. ISO
    // timestamp marks deletion; null clears (restore).
    | "deleted_at"
  >
>;

export const canonicalSchemaApi = {
  list: () =>
    disApiFetch<CanonicalSchemaResponse>(`/api/v1/dis/canonical-schema`),

  updateField: (
    domainId: string,
    fieldId: string,
    input: CanonicalSchemaFieldUpdateInput,
  ) =>
    disApiFetch<CanonicalSchemaField>(
      `/api/v1/dis/canonical-schema/${domainId}/${fieldId}`,
      { method: "PATCH", body: JSON.stringify(input) },
    ),

  addField: (domainId: string, input: CanonicalSchemaFieldCreateInput) =>
    disApiFetch<CanonicalSchemaField>(
      `/api/v1/dis/canonical-schema/${domainId}/fields`,
      { method: "POST", body: JSON.stringify(input) },
    ),

  bumpVersion: (domainId: string, input: CanonicalSchemaVersionBumpInput) =>
    disApiFetch<CanonicalSchemaDomain>(
      `/api/v1/dis/canonical-schema/${domainId}/version`,
      { method: "POST", body: JSON.stringify(input) },
    ),
};
