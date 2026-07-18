import { disApiFetch, disQs } from "./client";
import { parseCsvSlice } from "@/lib/dis/csv-parser";
import type { ListResponse } from "@/lib/api/types";
import type {
  ConfirmMappingInput,
  Upload,
  UploadDetail,
  UploadListParams,
} from "@/types/dis";

// Phase 5c.1a: list / get / create. The create() POST sends file
// metadata only, not the file blob itself, because:
//   1. MSW doesn't parse CSV in 5c.1a — column mapping is a 5c.1b
//      concern; the list/detail surfaces don't need parsed columns.
//   2. Real backend will likely want multipart/form-data when DIS
//      backend lands (Phase 5d). When that happens, this signature
//      changes — caller passes `file: File` and the body becomes
//      FormData. lib/api/client.ts (and lib/dis/api/client.ts by
//      mirror) auto-sets Content-Type: application/json for any
//      non-empty body without a Content-Type header; that auto-set
//      will need a `body instanceof FormData` guard added at that
//      time. Flagged here so the migration is obvious.
export const uploadsApi = {
  list: (params?: UploadListParams) =>
    disApiFetch<ListResponse<Upload>>(
      `/api/v1/dis/uploads${disQs(params as Record<string, unknown> | undefined)}`,
    ),

  get: (id: string) => disApiFetch<UploadDetail>(`/api/v1/dis/uploads/${id}`),

  // Idempotency-Key per call, matching the Ithina pattern in
  // lib/api/tenants.ts: a 500-then-retry produces two distinct intents.
  //
  // Phase 5c.1b hotfix: parses the CSV header + first 5 data rows on
  // the client and ships them in the POST body (`headers`,
  // `sample_rows`). MSW uses these to synthesize plausible
  // column_mappings via a heuristic mapper against the canonical
  // schema. Real backend (Phase 5d) parses server-side; the client
  // parse becomes redundant and these body fields drop. Non-CSV files
  // fall through with parsed=null and the MSW handler uses placeholder
  // columns.
  create: async (file: File, templateId?: string | null) => {
    const parsed = await parseCsvSlice(file).catch(() => null);
    return disApiFetch<Upload>(`/api/v1/dis/uploads`, {
      method: "POST",
      body: JSON.stringify({
        file_name: file.name,
        file_size_bytes: file.size,
        template_id: templateId ?? null,
        headers: parsed?.headers ?? null,
        sample_rows: parsed?.sample_rows ?? null,
      }),
      headers: {
        "Idempotency-Key": crypto.randomUUID(),
      },
    });
  },

  confirmMapping: (id: string, input: ConfirmMappingInput) =>
    disApiFetch<Upload>(`/api/v1/dis/uploads/${id}/confirm-mapping`, {
      method: "POST",
      body: JSON.stringify(input),
      headers: {
        "Idempotency-Key": crypto.randomUUID(),
      },
    }),
};
