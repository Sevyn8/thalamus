// Hand-maintained DIS types. Mirrors the role of types/api.ts on the
// Ithina side: all hand-maintained types live here until the DIS backend
// ships an OpenAPI spec, at which point `pnpm gen:dis-types` populates
// types/dis-openapi-generated.ts and surfaces migrate from this file
// to re-exports of the generated names (Phase 5d migration discipline).
//
// Phase 5c.1a: Upload list + detail metadata.
// Phase 5c.1b: Canonical schema + column mappings + LLM proposal metadata.
// Phase 5c.1c: PII redaction tags + tenant DIS settings + audit-log shapes.

export type UploadStatus =
  | "PENDING_REVIEW"
  | "CONFIRMED"
  | "MID_INGEST"
  | "COMPLETED"
  | "FAILED_VALIDATION";

// List-row shape for /dis/uploads. Carries enough for the table view
// plus tenant fields so Anjali's fleet view can show a tenant column.
export type Upload = {
  id: string;
  file_name: string;
  file_size_bytes: number;
  status: UploadStatus;
  template_id: string | null;
  template_name: string | null;
  rows_ingested: number | null;
  uploaded_by_user_id: string;
  uploaded_by_name: string;
  uploaded_at: string;
  tenant_id: string;
  tenant_name: string;
};

// Canonical schema. Phase 5c.1b shipped the minimum surface (id /
// name / description / type / synonyms / pii) for the mapping-review
// dropdown. Phase 5c.7a extends the field + domain shape with the
// metadata the browse pages render (display_name / required /
// nullable / unique / business_owner / example_values / constraints /
// referenced_by on fields; version / effective_date / field_count on
// domains). All extensions are optional to keep backwards
// compatibility with existing consumers (mapping review, templates).
//
// Phase 5d real-backend cutover may revisit the optional-vs-required
// shape; for now keeping mixed-old-and-new-fields is the safe trade.

export type CanonicalSchemaFieldType =
  | "string"
  | "number"
  | "datetime"
  | "boolean"
  | "enum";

export type CanonicalSchemaField = {
  id: string;            // e.g. "sales.transaction_id"
  name: string;          // e.g. "transaction_id"
  description: string;
  type: CanonicalSchemaFieldType;
  synonyms: string[];
  // pii flag is captured server-side from day one; Phase 5c.1c's
  // redaction layer reads it. Renderers in 5c.1b ignore the flag.
  pii: boolean;
  // Phase 5c.7a: optional metadata for the browse pages. All optional
  // for backwards compat — mapping-review and template surfaces only
  // read the original 6 fields above.
  display_name?: string;
  required?: boolean;
  nullable?: boolean;
  unique?: boolean;
  business_owner?: string;
  example_values?: string[];
  // Constraint descriptions as strings ("must be ISO 4217 currency
  // code", "non-negative", etc.). Real backend may structure later
  // as typed validators; v1 is documentation.
  constraints?: string[];
  // Denormalized count of templates + sources + validation rules
  // referencing this field. Real backend computes; v1 ships
  // denormalized so the field detail page doesn't N+1 cross-resource
  // queries. Same pattern as recent_event_count_30d on alert rules.
  referenced_by?: number;
  // Phase 5d.6: soft-delete state. null/undefined = active. ISO
  // timestamp = soft-deleted at that moment. Downstream references
  // (ColumnMappings, ValidationRules, Templates) continue to function
  // because canonical_field_id still resolves logically — soft-delete
  // is presentation-only filtering, not cascading data deletion. See
  // BUILD_PLAN 5d.6 closeout for the architectural decision rationale.
  deleted_at?: string | null;
};

export type CanonicalSchemaDomain = {
  id: string;            // e.g. "sales"
  name: string;          // e.g. "Sales"
  description: string;
  fields: CanonicalSchemaField[];
  // Phase 5c.7a: optional governance metadata. Single current version
  // per domain in v1; version diff view defers to Phase 5d.
  version?: string;            // e.g. "v1"
  effective_date?: string;     // ISO date when this version became active
  field_count?: number;        // denormalized fields.length for fleet sort
  // Phase 5c.8b2: timestamp of the most recent successful version bump.
  // Null on freshly-seeded fixture (never bumped). Drives "pending
  // since last bump" computation on the BumpVersionModal aggregator.
  last_bumped_at?: string | null;
  // Phase 5c.8b2: optional pending-change list (overrides + adds since
  // last bump). Server includes this on the schema GET response so the
  // BumpVersionModal can drive its summary panel without a second
  // round-trip. Real backend will likely shape this similarly.
  pending_changes?: PendingChangeWire[];
};

// Phase 5c.8b2: wire shape for a pending canonical-schema change.
// Two kinds: an edit applied to an existing field (carries the
// pre-override snapshot so the classifier can run on the client),
// or an entirely new field. Lives alongside the domain on the GET
// response.
export type PendingChangeWire =
  | {
      kind: "edit";
      field_id: string;
      override: Partial<CanonicalSchemaField>;
      before_field: CanonicalSchemaField;
    }
  | { kind: "add"; field: CanonicalSchemaField };

// Phase 5c.8b2: payload shapes for canonical-schema write surfaces.
// Add field requires id + name + type; everything else carries the
// agreed defaults from ambiguity v.
export type CanonicalSchemaFieldCreateInput = {
  id: string;
  name: string;
  type: CanonicalSchemaFieldType;
  display_name?: string;
  description?: string;
  required?: boolean;
  nullable?: boolean;
  unique?: boolean;
  pii?: boolean;
  business_owner?: string;
  example_values?: string[];
  constraints?: string[];
  synonyms?: string[];
};

// Bump version: callers post the next version string + the aggregated
// change_count + classification kind so the audit-trail captures
// what the bump committed without a join later.
export type CanonicalSchemaVersionBumpInput = {
  next_version: string;
  change_count: number;
  kind: "additive" | "breaking" | "neutral";
};

// Per-column LLM mapping proposal. Optional on a column row: when
// llm_proposal_metadata.enabled is false, the handler omits this
// field server-side, and the client never tries to render it. Single
// source of truth for the gate state (no metadata-vs-presence split).
export type MappingProposal = {
  canonical_field_id: string;
  // 0..1 confidence. Threshold buckets per Phase 5c.1b A8 amendment:
  //   high  >= 0.85
  //   medium 0.6 .. 0.85
  //   low   <  0.6
  // Real Gemini distributions may shift these in 5d.
  confidence: number;
};

// One row in a per-upload mapping table.
//   - source_column: column name from the uploaded CSV
//   - sample_values: up to 3 values, fixture-curated non-PII in 5c.1b
//   - llm_proposal: present only when LLM-on (handler omits when off)
//   - current_mapping: confirmed canonical_field_id (null until confirmed)
//   - canonical_field_label: denormalized for read-only summary view of
//       CONFIRMED/MID_INGEST/COMPLETED/FAILED_VALIDATION uploads, so
//       the client doesn't need a canonical-schema lookup just to
//       render an already-confirmed row label
//   - ignored: tenant marked the column as not relevant
export type ColumnMapping = {
  source_column: string;
  sample_values: string[];
  llm_proposal?: MappingProposal;
  current_mapping: string | null;
  canonical_field_label: string | null;
  ignored: boolean;
};

// Phase 5c.1b: model + model_version captured from day one even though
// tenants don't see them in v1. Admin LLM-ops in 5c.8 reads these fields
// for prompt/model lineage. v1 ships Gemini only; multi-model designed
// for from 5c.8 onward (see docs/dis-surface-map.md).
export type LlmProposalMetadata = {
  enabled: boolean;
  model: string;
  model_version: string;
  generated_at: string | null;
};

// Detail shape for /dis/uploads/[id]. Extends the list row with mapping
// review payload. column_mappings is null for uploads that haven't been
// processed enough to have any column metadata yet (defensive; not
// expected with current fixtures).
export type UploadDetail = Upload & {
  column_mappings: ColumnMapping[];
  llm_proposal_metadata: LlmProposalMetadata;
};

export type UploadListParams = {
  status?: UploadStatus | UploadStatus[];
  search?: string;
  offset?: number;
  limit?: number;
};

export type CreateUploadInput = {
  file_name: string;
  file_size_bytes: number;
  template_id?: string | null;
};

// Confirm-mapping payload. Map of source_column -> canonical_field_id
// for the columns the tenant chose to map; ignored_columns lists the
// source columns the tenant marked as not relevant. Single PATCH-on-
// confirm pattern (no per-cell autosave); see Phase 5c.1b plan Sb.
export type ConfirmMappingInput = {
  mappings: Record<string, string>;
  ignored_columns: string[];
};

// DIS tenant settings (Phase 5c.1c). LLM-assist hierarchy is exposed
// as three booleans that the UI can render directly:
//   capability: Module Access plan-level toggle (admin-controlled).
//               Hardcoded true in v1 MSW. Phase 5e wires real Module
//               Access checks.
//   opt_in:     tenant preference (tenant-controlled). Toggled from
//               /dis/settings, persisted per-tenant in localStorage.
//   effective:  capability && opt_in. The single signal MappingReviewView
//               and the upload-detail handler consume.
export type DisTenantSettings = {
  tenant_id: string | null;
  llm_assist: {
    capability: boolean;
    opt_in: boolean;
    effective: boolean;
  };
};

export type UpdateDisSettingsInput = {
  llm_assist_opt_in?: boolean;
};

// Source types — Phase 5c.2a. The 9 variants reflect named POS/retail
// connectors (Square, Lightspeed, Shopify POS, Toast, Clover) plus
// generic catch-alls for unlisted POS systems and arbitrary REST APIs,
// scheduled CSV pulls, and FTP feeds. CSV one-off uploads stay on
// /dis/uploads (different surface, different lifecycle); they aren't a
// "source" in the recurring-feed sense.
//
// Brand iconography for the named connectors is intentionally NOT
// shipped in v1 — pending legal review. SystemKindChip uses generic
// lucide Plug for all 5 named POS connectors plus a brand text label.
// Brand SVGs land post-legal-clear, likely Phase 5e or later.
export type SystemKind =
  | "CSV_SCHEDULED"
  | "SQUARE"
  | "LIGHTSPEED"
  | "SHOPIFY_POS"
  | "TOAST"
  | "CLOVER"
  | "POS_API_GENERIC"
  | "FTP"
  | "REST_API_GENERIC";

// Phase 5e.4c: Source-the-system status. Same 4 values as the legacy
// SourceStatus pre-split; the values' meaning narrows at the system
// level (ACTIVE = credentials valid + test passed; PAUSED = admin-
// paused the whole system; ERROR = credentials test failing;
// ONBOARDING = no credentials yet). Stream-level status lives on
// StreamStatus, declared independently so future divergence doesn't
// ripple (see [[source-stream-id-mapping]] for the parallel pattern).
export type SystemStatus = "ACTIVE" | "PAUSED" | "ERROR" | "ONBOARDING";

export type StreamHealth = "HEALTHY" | "DEGRADED" | "FAILING" | "UNKNOWN";

// Phase 5c.2a: connection_config is opaque (Record<string, unknown>).
// 5c.2b defines the discriminated union per source type when the
// create wizard needs to construct each variant's fields. 5c.2c reads
// it back per-type for the read-only Config tab on the detail page.
//
// Credentials are stored as opaque references in v1 (e.g.
// "secret://kowalski/pos-api-token"). UI never displays the raw
// secret; no permission family for credential raw-view in v1. Real
// backend integrates Cloud Secret Manager in Phase 5d.
export type Source = {
  id: string;
  name: string;
  type: SystemKind;
  status: SystemStatus;
  // Phase 5e.4c: stream_count denorm. Computed server-side in MSW;
  // real backend equivalent will compute via JOIN on streams table.
  // Phase 5e.4e: Source.health / schedule / last_run_at removed.
  // Health derives from runs (per-stream); schedule + last_run_at
  // live on Stream per the Source/Stream split. Stream.* is the
  // load-bearing surface for all three concerns.
  stream_count: number;
  // Org-node assignment — single-node per source per Phase 5c.2 plan
  // (resolved decision #5 in the surface map; multi-attach deferred
  // to v2). Surfaced as code + name for read paths; the source-create
  // wizard in 5c.2b uses the extracted OrgNodePicker to set it.
  org_node_id: string | null;
  org_node_code: string | null;
  org_node_name: string | null;
  connection_config: Record<string, unknown>;
  // Tenant attribution for Anjali's fleet view; same pattern as Upload.
  tenant_id: string;
  tenant_name: string;
  // Owner — the tenant user designated as the source's primary
  // operator. Surface-map calls for "reassign ownership" as an admin
  // action; that lands in 5c.2c.
  owner_user_id: string | null;
  owner_name: string | null;
  // Phase 5c.2c3: true when the tenant skipped the test-connection step
  // at source creation OR onboarding completion. Audit-trail flag, not
  // operational state — persists indefinitely (per A14). Surfaced as a
  // small amber chip next to the Status chip on the detail page.
  untested_at_creation: boolean;
  created_at: string;
  updated_at: string;
};

export type SourceDetail = Source;

export type SourceListParams = {
  type?: SystemKind | SystemKind[];
  status?: SystemStatus | SystemStatus[];
  search?: string;
  tenant_id?: string;
  offset?: number;
  limit?: number;
};

// Phase 5c.2b1: 3-step wizard payload (Type → OrgNode → Schedule).
// connection_config opaque in 5c.2b1's flow path; 5c.2b2 fills it via
// the per-type ConnectionConfig discriminated union. MSW POST handler
// sets status: ACTIVE when connection_config is non-empty (5c.2b2 full
// 5-step flow), ONBOARDING when empty (5c.2b1 3-step flow path).
export type CreateSourceInput = {
  name: string;
  type: SystemKind;
  org_node_id: string;
  // Phase 5e.4d: schedule optional. Pre-split CreateSource carried a
  // schedule (Source had its own cron); post-split schedule belongs to
  // Stream. AddSourceWizard no longer collects a schedule. Legacy
  // POSTs may still include it for back-compat; handler tolerates.
  schedule?: string;
  connection_config: Record<string, unknown>;
  // Phase 5c.2c3: optional; defaults to false on backend if omitted.
  // True when the tenant skipped the test-connection step at creation.
  untested_at_creation?: boolean;
};

// Phase 5c.2b2: ConnectionConfig discriminated union per source type.
// 9 variants matching SystemKind. Each form component fills its
// variant's fields; type-narrowing happens at the form/switchboard
// boundary via the `type` discriminator. The wizard's draft state
// holds Partial<ConnectionConfig> until validated; on submit it
// becomes the full union variant for the source's type.
//
// Credentials are stored as opaque references in v1 (e.g.
// "secret://kowalski/square-prod"). Real backend integrates Cloud
// Secret Manager in Phase 5d. UI never displays raw secrets.

export type Environment = "sandbox" | "production";
export type AuthType = "basic" | "bearer" | "api_key";

export type ConnectionConfig =
  | {
      type: "SQUARE";
      merchant_id: string;
      location_id: string;
      environment: Environment;
    }
  | { type: "LIGHTSPEED"; account_id: string; environment: Environment }
  | { type: "SHOPIFY_POS"; shop_domain: string }
  | { type: "TOAST"; restaurant_guid: string; environment: Environment }
  | { type: "CLOVER"; merchant_id: string; environment: Environment }
  | {
      type: "POS_API_GENERIC";
      endpoint_url: string;
      auth_type: AuthType;
      credentials_ref: string;
    }
  | { type: "CSV_SCHEDULED"; file_pattern: string; source_url_or_ftp: string }
  | {
      type: "FTP";
      host: string;
      port: number;
      path: string;
      username: string;
      credentials_ref: string;
    }
  | {
      type: "REST_API_GENERIC";
      endpoint_url: string;
      auth_type: AuthType;
      credentials_ref: string;
      headers: Record<string, string>;
    };

export type TestConnectionRequest = {
  type: SystemKind;
  connection_config: Record<string, unknown>;
};

export type ConnectionTestErrorCode =
  | "AUTHENTICATION_FAILED"
  | "HOST_UNREACHABLE"
  | "SCHEMA_MISMATCH"
  | "TIMEOUT";

export type TestConnectionResult =
  | { success: true }
  | {
      success: false;
      error_code: ConnectionTestErrorCode;
      error_message: string;
    };

// Phase 5c.2c1: edit-form payload. type and org_node_id are immutable
// post-creation per Sb/Sc; edit doesn't surface them. Saving with
// non-empty connection_config on an ONBOARDING source flips status
// to ACTIVE in the same update call (per A4) — no separate
// "complete onboarding" endpoint.
export type UpdateSourceInput = {
  name?: string;
  // Phase 5e.4e: schedule field dropped. SourceEditForm no longer
  // collects a schedule; per-feed cadence lives on Stream + its own
  // PATCH endpoint.
  connection_config?: Record<string, unknown>;
  owner_user_id?: string | null;
  // Phase 5c.2c3 / 5e.7b: set by AddSourceWizard when the tenant
  // skips the Test step at creation. Persists indefinitely once true
  // (audit trail). ContinueOnboardingFlow used to also set this on
  // legacy ONBOARDING-source completion; that flow retired in 5e.7b.
  untested_at_creation?: boolean;
};

// Phase 5c.2c2: bulk action result. Per-source success/failure with
// optional error code + message. Allows partial success — 2 of 3 OK,
// 1 skipped (already paused) — surfaced in toast UX.
export type BulkActionResultItem = {
  source_id: string;
  success: boolean;
  error_code?: string;
  error_message?: string;
};

export type BulkActionResponse = {
  results: BulkActionResultItem[];
};

// Phase 5e.4a: Stream = one data feed sourced from a parent Source.
// Source = the external system identity (Shopify, Square, FTP host)
// carrying credentials + connection_config. Stream = one feed off that
// system (Shopify orders / Shopify inventory / etc.), carrying its own
// domain + schedule. A Source can have many Streams; v1 fixtures
// exercise the Shopify orders+inventory case via fork on source_id
// 01958900-0001-7000-8000-000000000006.
//
// Foundation chunk: types + handlers + fixtures only; no UI changes.
// Dependent types (Run, ValidationRule, DriftEvent, Freshness,
// AlertEvent, AlertRule, Backfill) gain stream_id alongside the
// existing source_id during the transition window.
//
// Phase 5e.4e finding (revised from 5e.4a plan): the
// source_id + source_name + source_type triple on dependent types
// STAYS as load-bearing display denorm. 12+ surfaces (fleet tables,
// detail-page subtitles, parent-source cross-links) read source_name
// to show "which system produced this signal" without an N+1 join.
// source_type drives SystemKindChip. source_id powers handler-side
// back-compat filtering, RunErrorPanel's Run-now CTA, and admin-fleet
// aggregation. The triple is by-design permanent, not transitional.

// Stream domain — what the feed delivers. Values match
// CanonicalSchemaDomain.id (sales / inventory / customers / suppliers /
// stores / products), per the TemplateDomain precedent
// (types/dis.ts:941). Declared independently so future divergence
// (e.g. events / audit_log streams that have no canonical-schema
// counterpart) doesn't ripple back through Template / CanonicalSchema.
export type StreamDomain =
  | "sales"
  | "inventory"
  | "customers"
  | "suppliers"
  | "stores"
  | "products";

// Phase 5e.4c: StreamStatus declared independently (no longer aliased
// to SystemStatus). Same 4 values for v1, but the types are
// distinct — Stream-level status means "feed scheduled and running"
// (ACTIVE) / "feed-level paused" (PAUSED) / "last run failed" (ERROR)
// / "no schedule yet" (ONBOARDING). System-level meanings live on
// SystemStatus. Values may diverge in a future phase when real
// backend semantics demand; alias break costs nothing now.
export type StreamStatus = "ACTIVE" | "PAUSED" | "ERROR" | "ONBOARDING";

export type Stream = {
  id: string;
  // FK to the parent Source (system identity). One source → many streams.
  source_id: string;
  // Denormalized for fleet-view rendering without per-row source GET.
  // Phase 5e.4e finding: stays as load-bearing display denorm —
  // StreamsTable row subtitle + Stream detail page subtitle both
  // render source_name; pruning would require a follow-up GET per row.
  source_name: string;
  system_kind: SystemKind;
  // Feed display name (Stream-the-feed reads "name", e.g.
  // "Buc-ee's Shopify — orders"). Distinct from Source-the-system's
  // display name (which 5e.4c clarifies).
  name: string;
  domain: StreamDomain;
  schedule: string | null;
  status: StreamStatus;
  health: StreamHealth;
  last_run_at: string | null;
  // Tenant attribution mirrors Source — Stream rows surface in
  // tenant-scoped fleet tables, so the denorm is load-bearing.
  tenant_id: string;
  tenant_name: string;
  created_at: string;
  updated_at: string;
};

// Phase 5e.4a-5e.4d: Stream create payload. AddStreamWizard (5e.4d)
// builds this shape from its 4-step (or 3-step pre-bound) flow:
// source_id from URL param or picker step; name + domain + schedule
// from the remaining steps.
export type CreateStreamInput = {
  source_id: string;
  name: string;
  domain: StreamDomain;
  schedule: string;
};

// Phase 5e.4d: PATCH update payload for streams. Mirrors UpdateSource-
// Input's optional-fields shape. source_id and domain are immutable
// post-creation (same rationale as Source.type / Source.org_node_id);
// edit doesn't surface them.
export type UpdateStreamInput = {
  name?: string;
  schedule?: string;
};

export type StreamListParams = {
  source_id?: string;
  domain?: StreamDomain | StreamDomain[];
  status?: StreamStatus | StreamStatus[];
  tenant_id?: string;
  offset?: number;
  limit?: number;
};

// Phase 5c.3a: Run = one ingest attempt for a Source. Carries enough
// for both the per-source Runs tab AND the cross-tenant fleet view
// (5c.3b /dis/runs page) without requiring joins on the client side.
//
// Denormalized fields:
//   source_name / source_type — fleet table column (avoids fetching
//     the source detail per row)
//   tenant_id / tenant_name — fleet tenant column (Anjali's view)
//   triggered_by_user_name — when triggered_by === MANUAL, set to the
//     user's display name at trigger time. Hydrated server-side so MSW
//     doesn't need to join against tenant-users (alias dance avoided
//     per #10 in 5c.3a plan). For SCHEDULE / BACKFILL / API the user
//     fields are null.
//
// Status semantics:
//   QUEUED — accepted, waiting to start (started_at null)
//   RUNNING — in progress (started_at set, finished_at null)
//   SUCCEEDED — finished cleanly
//   FAILED — finished with error (error_code + error_message set)
//   CANCELED — user/admin canceled before completion (5d concern;
//     fixtures don't seed this in v1)

export type RunStatus =
  | "QUEUED"
  | "RUNNING"
  | "SUCCEEDED"
  | "FAILED"
  | "CANCELED";

export type RunTriggeredBy = "SCHEDULE" | "MANUAL" | "BACKFILL" | "API";

export type Run = {
  id: string;
  source_id: string;
  source_name: string;
  source_type: SystemKind;
  // Phase 5e.4a denorms; per 5e.4e audit: source_id + source_name +
  // source_type stay as load-bearing display denorms (RunsTable fleet
  // row, RunDetailHeader subtitle + chip, RunErrorPanel run-now CTA,
  // admin-fleet stale-source aggregation). stream_id is the
  // additional FK powering per-stream filtering + per-stream Run-now;
  // v1 dependents are 1:1 with sources except the Shopify
  // orders+inventory fork.
  stream_id: string;
  stream_name: string;
  tenant_id: string;
  tenant_name: string;
  status: RunStatus;
  triggered_by: RunTriggeredBy;
  triggered_by_user_id: string | null;
  triggered_by_user_name: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  rows_ingested: number | null;
  rows_failed: number | null;
  rows_skipped: number | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
};

export type RunListParams = {
  source_id?: string;
  stream_id?: string;
  status?: RunStatus | RunStatus[];
  triggered_by?: RunTriggeredBy | RunTriggeredBy[];
  // ISO-8601 timestamps; backend filters runs whose started_at falls
  // in the inclusive range. Date-range presets compose these on the
  // client side (today / 7d / 30d in 5c.3b).
  started_after?: string;
  started_before?: string;
  tenant_id?: string;
  offset?: number;
  limit?: number;
};

// Phase 5c.4a: validation surface.
//
// ValidationRule = a column-level constraint that runs against each
// ingested row of a source. ValidationViolation = a single row that
// failed a rule, linked back to the run that produced it.
//
// 5 rule types in v1: REGEX (pattern match), RANGE (numeric bounds),
// NULL_CHECK (presence required), ENUM (allowed values), CUSTOM
// (free-form server-side logic; UI just shows the description).
//
// Read-only in 5c.4a — rule create/edit/disable lands when the DIS
// backend supports rule mutation (Phase 5d or later). Detail page
// renders rule definition + violation log; no inline edit.
//
// Denormalized fields on the wire (matching Run pattern):
//   source_name / source_type — fleet table column
//   tenant_id / tenant_name — fleet tenant column
//   recent_violation_count / last_violation_at — list-view summary
//     (avoids N+1 violations queries to render the rules table)

export type ValidationRuleType =
  | "REGEX"
  | "RANGE"
  | "NULL_CHECK"
  | "ENUM"
  | "CUSTOM";

export type ValidationSeverity = "ERROR" | "WARNING" | "INFO";

export type ValidationRuleStatus = "ACTIVE" | "DISABLED";

export type ValidationRule = {
  id: string;
  name: string;
  description: string;
  type: ValidationRuleType;
  severity: ValidationSeverity;
  status: ValidationRuleStatus;
  // Column the rule targets. Null for CUSTOM rules that span multiple
  // columns (e.g. "qty * unit_price = total_amount").
  target_column: string | null;
  // Type-specific configuration. Shape varies by rule type — UI reads
  // it via discriminated narrowing. Real backend will likely strongly
  // type this; v1 keeps it as Record for fixture flexibility.
  parameters: Record<string, unknown>;
  source_id: string;
  source_name: string;
  source_type: SystemKind;
  // Phase 5e.4a denorms; per 5e.4e audit they stay as load-bearing
  // display + filter fields. See Run type for the rationale.
  stream_id: string;
  stream_name: string;
  tenant_id: string;
  tenant_name: string;
  recent_violation_count: number;
  last_violation_at: string | null;
  created_at: string;
  updated_at: string;
};

export type ValidationViolation = {
  id: string;
  rule_id: string;
  // Run that produced the failing row.
  run_id: string;
  // 1-based row index within the run's ingested batch.
  row_index: number;
  // The actual value that failed. Pre-redacted server-side for PII
  // columns (Phase 5c.1c PII layer would flag the rule's
  // target_column; redaction lands at the source). v1 fixture stores
  // raw values for non-PII rules; PII columns hold redacted markers.
  value: string;
  // Human-readable failure message.
  message: string;
  created_at: string;
};

export type ValidationListParams = {
  source_id?: string;
  stream_id?: string;
  severity?: ValidationSeverity | ValidationSeverity[];
  status?: ValidationRuleStatus | ValidationRuleStatus[];
  tenant_id?: string;
  search?: string;
  offset?: number;
  limit?: number;
};

// Phase 5c.4b: schema drift surface.
//
// DriftEvent = a single observation of source schema diverging from
// the canonical schema, detected when a run ingests rows. 4 event
// types in v1 (enum-value-changed, length-constraint-changed deferred
// to a future phase).
//
// before/after fields are typed null when the event type makes them
// inapplicable — null on `before_*` for COLUMN_ADDED, null on
// `after_*` for COLUMN_REMOVED. formatDriftDiff() inline in the
// drift-events table renders the appropriate string per shape.
//
// Read-only in 5c.4b — drift events are detected by ingest, not
// configured by the tenant. Acknowledge / dismiss workflows defer
// to Phase 5d backend support.

export type DriftEventType =
  | "COLUMN_ADDED"
  | "COLUMN_REMOVED"
  | "TYPE_CHANGED"
  | "NULLABILITY_CHANGED";

export type DriftSeverity = "BREAKING" | "WARNING" | "INFO";

export type DriftEvent = {
  id: string;
  source_id: string;
  source_name: string;
  source_type: SystemKind;
  // Phase 5e.4a denorms; per 5e.4e audit they stay as load-bearing
  // display + filter fields. See Run type for the rationale.
  stream_id: string;
  stream_name: string;
  tenant_id: string;
  tenant_name: string;
  // Run that detected the drift (the ingest pipeline observation
  // moment). Click-through navigates to /dis/runs/[run_id].
  run_id: string;
  event_type: DriftEventType;
  severity: DriftSeverity;
  column_name: string;
  // Null when inapplicable (e.g., before_type=null for COLUMN_ADDED).
  before_type: string | null;
  after_type: string | null;
  before_nullable: boolean | null;
  after_nullable: boolean | null;
  description: string;
  detected_at: string;
  created_at: string;
};

export type DriftListParams = {
  source_id?: string;
  stream_id?: string;
  severity?: DriftSeverity | DriftSeverity[];
  event_type?: DriftEventType | DriftEventType[];
  tenant_id?: string;
  offset?: number;
  limit?: number;
};

// Phase 5c.4c: data freshness surface.
//
// Freshness = per-source SLO record. v1 is 1:1 with source (id =
// source_id) — multi-SLO-per-source (e.g., separate freshness
// expectations for sales vs inventory domains) defers to whenever
// real backend introduces it. URL convention reflects that v1
// simplification (/dis/freshness/[id] = source_id); API path
// /api/v1/dis/freshness/sources/[source_id] is forward-compatible
// for the schema change.
//
// State priority (most-actionable first): CRITICAL > STALE >
// DELAYED > FRESH > UNKNOWN.
//   - FRESH: within expected window
//   - DELAYED: past expected but within ~2x staleness threshold
//   - STALE: past tolerance
//   - CRITICAL: no data >24h on a source expected hourly+
//   - UNKNOWN: ONBOARDING / no data history yet
//
// State-transition workflows (acknowledge / resolve) defer to Phase
// 5d backend support — same shape as drift events.
//
// Cross-link to alerts (5c.4d): "View related alerts" CTA on the
// detail view lands when alerts ships in the next chunk.

export type FreshnessState =
  | "FRESH"
  | "DELAYED"
  | "STALE"
  | "CRITICAL"
  | "UNKNOWN";

// State-transition history. Real backend will log every staleness
// check; v1 fixture seeds 5-8 transitions per source over the last
// 30 days as embedded `recent_history` on the parent Freshness
// record. Sufficient for demo without a separate sub-collection.
export type FreshnessHistoryEvent = {
  occurred_at: string;
  previous_state: FreshnessState | null;
  new_state: FreshnessState;
};

export type Freshness = {
  // id === source_id in v1. Real backend may diverge; consumers
  // navigate via source_id and the detail page resolves either way.
  // Phase 5e.4a transitional: id === stream_id in the new mapping
  // (v1 fixtures are 1:1 except Shopify orders+inventory fork, which
  // each get their own Freshness row at the stream level — exercising
  // the multi-SLO-per-source case anticipated by the 5c.4c comment
  // above).
  id: string;
  source_id: string;
  source_name: string;
  source_type: SystemKind;
  stream_id: string;
  stream_name: string;
  tenant_id: string;
  tenant_name: string;
  // Humanized label ("Every 15 minutes" / "Hourly" / etc.). Real
  // backend computes from source.schedule cron; v1 ships
  // denormalized so the surface doesn't depend on the cron humanizer.
  expected_frequency: string;
  staleness_threshold_seconds: number;
  // Last successful run with non-zero rows. Null for ONBOARDING /
  // never-ingested sources.
  last_data_received_at: string | null;
  current_state: FreshnessState;
  // 0 when fresh; growing for DELAYED/STALE/CRITICAL.
  delay_seconds: number;
  breach_count_30d: number;
  recent_history: FreshnessHistoryEvent[];
  created_at: string;
  updated_at: string;
};

export type FreshnessListParams = {
  state?: FreshnessState | FreshnessState[];
  source_id?: string;
  stream_id?: string;
  tenant_id?: string;
  offset?: number;
  limit?: number;
};

// Phase 5c.4d-events: alert events surface.
//
// Read-only in v1; acknowledge/resolve workflows defer to Phase 5d
// backend support (same pattern as validation rules, drift events,
// freshness state transitions). Fixtures seed ack/resolve metadata
// so the detail page demonstrates the state-transition story without
// UI mutations.
//
// 5 trigger types in v1 (covers the demo narrative):
//   FRESHNESS_STALE / FRESHNESS_CRITICAL → freshness state breach
//   RUN_FAILURE_STREAK                   → N consecutive run failures
//   VALIDATION_VIOLATION_THRESHOLD       → severity-ERROR violation count
//   SCHEMA_DRIFT_BREAKING                → BREAKING drift event
//
// trigger_ref_id is polymorphic. The detail page reads trigger_type
// to construct the correct deep-link via a switch with assertNever
// exhaustiveness:
//   FRESHNESS_STALE / FRESHNESS_CRITICAL → /dis/freshness/{source_id}
//   RUN_FAILURE_STREAK                   → /dis/runs/{run_id}
//   VALIDATION_VIOLATION_THRESHOLD       → /dis/validation/rules/{rule_id}
//   SCHEMA_DRIFT_BREAKING                → /dis/validation/drift/{event_id}
//
// State priority (most-actionable first): UNRESOLVED > ACKNOWLEDGED >
// RESOLVED. SUPPRESSED / EXPIRED / CANCELED defer to a future state
// model expansion when real-backend mutation lands.

export type AlertEventState = "UNRESOLVED" | "ACKNOWLEDGED" | "RESOLVED";

export type AlertSeverity = "CRITICAL" | "WARNING" | "INFO";

export type AlertChannel = "SLACK" | "EMAIL" | "PAGERDUTY" | "WEBHOOK";

export type AlertTriggerType =
  | "FRESHNESS_STALE"
  | "FRESHNESS_CRITICAL"
  | "RUN_FAILURE_STREAK"
  | "VALIDATION_VIOLATION_THRESHOLD"
  | "SCHEMA_DRIFT_BREAKING";

export type AlertEvent = {
  id: string;
  source_id: string;
  source_name: string;
  source_type: SystemKind;
  // Phase 5e.4a denorms; per 5e.4e audit they stay as load-bearing
  // display + filter fields. See Run type for the rationale.
  stream_id: string;
  stream_name: string;
  tenant_id: string;
  tenant_name: string;
  trigger_type: AlertTriggerType;
  // Polymorphic; interpretation depends on trigger_type (see module
  // comment for the mapping).
  trigger_ref_id: string;
  // Phase 5c.4d-rules: link back to the AlertRule that fired this
  // event. Null in v1 only for legacy seed-data; real backend sets
  // unconditionally. Powers the "Configured by rule" link on the
  // event detail page + the rule_id filter on AlertEventsTable
  // (used by rule detail's inline events list).
  rule_id: string | null;
  // Denormalized human-readable summary for the table cell. Real
  // backend would compute; v1 stores so the surface doesn't depend
  // on N+1 cross-table lookups.
  trigger_description: string;
  severity: AlertSeverity;
  state: AlertEventState;
  channel: AlertChannel;
  // Channel-specific destination string (e.g., "#ops-bucees" for
  // SLACK, "oncall@bucees.com" for EMAIL). Display-only.
  recipient: string;
  fired_at: string;
  // Null when state === UNRESOLVED.
  acknowledged_at: string | null;
  acknowledged_by_user_id: string | null;
  acknowledged_by_user_name: string | null;
  // Null unless state === RESOLVED.
  resolved_at: string | null;
  resolved_by_user_id: string | null;
  resolved_by_user_name: string | null;
  created_at: string;
  updated_at: string;
};

export type AlertEventListParams = {
  source_id?: string;
  stream_id?: string;
  rule_id?: string;
  state?: AlertEventState | AlertEventState[];
  severity?: AlertSeverity | AlertSeverity[];
  channel?: AlertChannel | AlertChannel[];
  trigger_type?: AlertTriggerType | AlertTriggerType[];
  tenant_id?: string;
  fired_after?: string;
  offset?: number;
  limit?: number;
};

// Phase 5c.4d-rules: alert rules surface.
//
// AlertRule = the configuration that decides what fires when. Read-
// only in v1; rule mutation defers to Phase 5d backend support
// alongside ack/resolve. Same pattern as validation rules / drift /
// freshness — mutation workflows ship as a coherent sweep when the
// backend supports them.
//
// Scope:
//   SOURCE — rule watches one specific source. source_id set.
//   FLEET  — rule watches all sources at the tenant level (or
//            organization-wide for platform-managed rules). source_id
//            null; source_name renders as "(any source)" in tables.
//
// trigger_type reuses the AlertEvent enum (5 variants). trigger_ref_id
// on events points at the operational signal that fired them; rules
// don't have a corresponding ref because the trigger is a continuous
// condition, not an event reference.
//
// trigger_threshold: a single human-readable string describing the
// firing condition. Real backend will likely structure this as a typed
// threshold object per trigger_type; v1 keeps it as opaque text so
// the surface stays simple. formatRuleSentence() in the detail page
// composes a natural-language sentence from the rule's fields.

export type AlertRuleScope = "SOURCE" | "FLEET";

export type AlertRule = {
  id: string;
  name: string;
  description: string;
  scope: AlertRuleScope;
  // Null when scope === "FLEET".
  source_id: string | null;
  source_name: string | null;
  source_type: SystemKind | null;
  // Phase 5e.4a denorms; per 5e.4e audit they stay as load-bearing
  // display + filter fields. Null for FLEET scope (matches source_id
  // null). For SOURCE-scope rules, stream_id is set when the rule
  // targets a specific feed; null when the rule applies to all
  // streams of a source.
  stream_id: string | null;
  stream_name: string | null;
  tenant_id: string;
  tenant_name: string;
  trigger_type: AlertTriggerType;
  // Human-readable threshold ("STALE for >2h" / "3+ consecutive
  // failures" / "violation count exceeds 100" / "any BREAKING drift").
  trigger_threshold: string;
  severity: AlertSeverity;
  channel: AlertChannel;
  recipient: string;
  enabled: boolean;
  created_at: string;
  created_by_user_id: string | null;
  created_by_user_name: string | null;
  // Denormalized event count over last 30 days. Real backend computes;
  // v1 ships denormalized so the fleet table doesn't N+1 a count query
  // per row.
  recent_event_count_30d: number;
  updated_at: string;
};

export type AlertRuleListParams = {
  source_id?: string;
  stream_id?: string;
  scope?: AlertRuleScope | AlertRuleScope[];
  enabled?: boolean;
  severity?: AlertSeverity | AlertSeverity[];
  trigger_type?: AlertTriggerType | AlertTriggerType[];
  tenant_id?: string;
  offset?: number;
  limit?: number;
};

// Phase 5c.8a: Fleet health surface (Anjali admin view).
//
// Aggregate operational signal matrix across all tenants. Synthesized
// MSW-side from existing operational fixtures (runs / freshness /
// alert-events / schema-drift-events); no real backend equivalent in
// v1 (no fleet-health endpoint shipped). Future-real path: backend
// computes server-side from the same source tables.
//
// 4 signals chosen for demo coverage:
//   failed_runs_24h    — runs.status === FAILED in trailing 24h
//   stale_sources      — distinct sources with freshness STALE/CRITICAL
//   unresolved_alerts  — alert-events with state UNRESOLVED/ACKNOWLEDGED
//   breaking_drift_24h — schema-drift severity BREAKING in trailing 24h

export type FleetHealthSignals = {
  failed_runs_24h: number;
  stale_sources: number;
  unresolved_alerts: number;
  breaking_drift_24h: number;
};

export type FleetHealthRow = {
  tenant_id: string;
  tenant_name: string;
  tier: string | null;          // hand-typed; matches Tenant.tier shape
  signals: FleetHealthSignals;
  // Sum across signals — drives "noisiest active first" sort.
  total_signals: number;
};

export type FleetHealthResponse = { items: FleetHealthRow[] };

// Phase 5c.5a: Templates surface.
//
// A Template is a reusable column → canonical-field mapping. Tenants
// who repeatedly ingest the same shape of data (same columns, same
// canonical mapping) save the mapping as a template and apply it on
// future uploads or sources, skipping the LLM-mapping + PII-redaction
// setup step.
//
// V1 is read-only: templates are seeded as fixtures (the capture
// flow — "save current upload's mapping as a template" — defers to
// a later chunk alongside the apply-template integrations on upload
// review and source-create wizard).
//
// Domain reuses CanonicalSchemaDomain id values verbatim (sales /
// inventory / customers / suppliers / stores / products) so a
// template's domain naturally aligns with its column_mappings'
// canonical_field_id parents. Defining a separate enum here would
// duplicate; if domain semantics ever diverge, lift then.
//
// Visibility:
//   PRIVATE       — only the creator can apply this template
//   TENANT_SHARED — any user in the creator's tenant can apply it
//
// Cross-tenant template sharing is NOT a v1 concept; visibility lives
// within a tenant boundary.

export type TemplateDomain =
  | "sales"
  | "inventory"
  | "customers"
  | "suppliers"
  | "stores"
  | "products";

export type TemplateVisibility = "PRIVATE" | "TENANT_SHARED";

// Phase 5e.6: discriminator on Template.
//   NORMAL — single-domain template; column_mappings all map to one
//            canonical domain. Created via save-from-upload capture
//            flow (deferred from 5c.5a; still not in UI).
//   SUPER  — multi-domain template; column_mappings span 2+ canonical
//            domains. Created via AddSuperTemplateWizard (5e.6). CSV
//            export concatenates per-domain canonical fields in
//            schema-grouped order.
export type TemplateKind = "NORMAL" | "SUPER";

export type TemplateColumnMapping = {
  source_column: string;
  canonical_field_id: string;
  // Denormalized for read-only render — same pattern as upload's
  // ColumnMapping.canonical_field_label (avoids canonical-schema
  // lookup per row).
  canonical_field_label: string;
  // Optional transformation (UPPERCASE / TRIM / ISO_DATE / etc.).
  // v1 stores opaque text; real backend may structure as a typed
  // transformation pipeline.
  transformation: string | null;
  // PII redaction at apply-time. Independent of canonical_field
  // pii flag because tenants may want to over-redact a non-flagged
  // field for their own compliance posture.
  redact_pii: boolean;
};

export type Template = {
  id: string;
  // Phase 5e.6: kind discriminator. NORMAL = single-domain (1 entry
  // in domains[]). SUPER = multi-domain (2+ entries).
  kind: TemplateKind;
  name: string;
  description: string;
  // Phase 5e.6: pre-split this was `domain: TemplateDomain` (single).
  // Migrated to `domains: TemplateDomain[]` so SUPER templates can
  // declare 2+ domain coverage. NORMAL templates carry a 1-element
  // array. TemplateColumnMapping.canonical_field_id continues to
  // carry the per-mapping domain prefix.
  domains: TemplateDomain[];
  visibility: TemplateVisibility;
  tenant_id: string;
  tenant_name: string;
  column_mappings: TemplateColumnMapping[];
  created_by_user_id: string;
  created_by_user_name: string;
  created_at: string;
  last_used_at: string | null;
  // Denormalized 30-day apply-count. Real backend computes; v1 ships
  // denormalized so the fleet table doesn't N+1 a count query per row.
  usage_count_30d: number;
  updated_at: string;
};

export type TemplateListParams = {
  // Phase 5e.6: filter matches via subset — domain in domains[].
  // SUPER templates that cover the requested domain match.
  domain?: TemplateDomain | TemplateDomain[];
  kind?: TemplateKind | TemplateKind[];
  visibility?: TemplateVisibility | TemplateVisibility[];
  tenant_id?: string;
  offset?: number;
  limit?: number;
};

// Phase 5e.6: SUPER-template creation payload. AddSuperTemplateWizard
// supplies domains (≥2) + name + description + visibility; server
// auto-populates column_mappings from each domain's canonical fields.
// NORMAL-kind creation defers (still no save-from-upload flow in UI).
export type CreateTemplateInput = {
  kind: TemplateKind;
  name: string;
  description: string;
  visibility: TemplateVisibility;
  domains: TemplateDomain[];
};

// Phase 5e.6: PATCH update — name/description/visibility only.
// Domains immutable (changing them would invalidate the derived
// column_mappings and any downstream upload referencing the template).
export type UpdateTemplateInput = {
  name?: string;
  description?: string;
  visibility?: TemplateVisibility;
};

// Phase 5c.6a: Backfills surface.
//
// A Backfill is a re-run-of-historical-window operation: when a source
// went broken for some time, the tenant requests a backfill once it's
// fixed, and the system spawns a sequence of Runs to re-ingest the
// window. Backfills are operations not configurations — different
// conceptually from continuous signals (runs/validation/drift/
// freshness/alerts).
//
// V1 is read-only: backfills are seeded as fixtures; cancel + request-
// backfill flows defer to Phase 5d backend support alongside ack/
// resolve and rule mutation.
//
// Status semantics:
//   QUEUED              — accepted, not yet started; spawned_run_ids empty
//   RUNNING             — at least one spawned run is in-flight
//   SUCCEEDED           — all spawned runs SUCCEEDED
//   PARTIALLY_SUCCEEDED — mix of SUCCEEDED + FAILED runs; some data
//                         re-ingested, some windows still gap
//   FAILED              — all spawned runs FAILED, or queue rejected
//                         the request before any run spawned
//   CANCELED            — tenant cancelled while QUEUED or RUNNING
//
// rows_ingested + rows_failed are denormalized roll-ups across the
// spawned runs. Real backend computes; v1 stores so the surface
// doesn't N+1 a count query per row.
//
// spawned_run_ids references real Run.id values — cross-link to
// /dis/runs/[run_id] on detail page. QUEUED entries carry an empty
// array; populated as runs spawn at apply-time on the real backend.

export type BackfillStatus =
  | "QUEUED"
  | "RUNNING"
  | "SUCCEEDED"
  | "PARTIALLY_SUCCEEDED"
  | "FAILED"
  | "CANCELED";

export type Backfill = {
  id: string;
  source_id: string;
  source_name: string;
  source_type: SystemKind;
  // Phase 5e.4a denorms; per 5e.4e audit they stay as load-bearing
  // display + filter fields. See Run type for the rationale.
  // Backfill is feed-scoped (you backfill one stream's window, not all
  // streams of a system), so stream_id is the load-bearing FK.
  stream_id: string;
  stream_name: string;
  tenant_id: string;
  tenant_name: string;
  window_start: string;
  window_end: string;
  status: BackfillStatus;
  requested_by_user_id: string;
  requested_by_user_name: string;
  requested_at: string;
  // QUEUED + RUNNING: ETA from the queue planner. Null otherwise.
  estimated_completion_at: string | null;
  // SUCCEEDED + PARTIALLY_SUCCEEDED + FAILED: actual completion time
  // of the last spawned run. Null while QUEUED/RUNNING/CANCELED.
  completed_at: string | null;
  // Roll-up across spawned runs.
  rows_ingested: number;
  rows_failed: number;
  // Run.id values that this backfill spawned. Empty for QUEUED;
  // populated as runs spawn through RUNNING/SUCCEEDED/etc.
  spawned_run_ids: string[];
  // FAILED only: human-readable summary. Null otherwise.
  error_summary: string | null;
  created_at: string;
  updated_at: string;
};

export type BackfillListParams = {
  source_id?: string;
  stream_id?: string;
  status?: BackfillStatus | BackfillStatus[];
  tenant_id?: string;
  offset?: number;
  limit?: number;
};

// Phase 5c.8c: LLM ops surface (Anjali admin view).
//
// Aggregate LLM call telemetry per tenant per Gemini variant.
// Read-only display; no real backend endpoint in v1 (Sanjeev has
// not shipped an LLM-ops endpoint per the 5e.1 OpenAPI diff). Real
// path lands when Vertex AI billing + telemetry export is wired.
//
// 4 Gemini variants in v1; the model field stays open via string
// so future variants land without type changes. 3 request-type
// categories matching actual DIS LLM call sites (column_mapping
// for upload mapping review, synonym_discovery for canonical-schema
// LLM enrichment, validator_synthesis for rule generation).

export type LlmOpsModel =
  | "gemini-1.5-flash"
  | "gemini-1.5-pro"
  | "gemini-2.0-flash"
  | "gemini-2.0-pro";

export type LlmOpsRequestType =
  | "column_mapping"
  | "synonym_discovery"
  | "validator_synthesis";

export type LlmOpsTimeWindow = "24h" | "7d" | "30d";

// Failure variants carry plausible Gemini error semantics. Mix these
// across the fixture failure log so Anjali sees diverse narratives.
export type LlmOpsErrorCode =
  | "RATE_LIMIT_EXCEEDED"
  | "TIMEOUT"
  | "CONTEXT_LENGTH_EXCEEDED"
  | "SAFETY_BLOCKED";

export type LlmOpsRequestEntry = {
  id: string;
  tenant_id: string;
  tenant_name: string;
  model: LlmOpsModel;
  request_type: LlmOpsRequestType;
  occurred_at: string;
  input_tokens: number;
  output_tokens: number;
  duration_ms: number;
  cost_usd: number;
  status: "SUCCESS" | "ERROR";
  error_code: LlmOpsErrorCode | null;
  error_message: string | null;
};

// Fleet row aggregations for the selected window. models_used is
// a denormalized list of the model names the tenant invoked in the
// window (not full per-model stats — that lives on the detail page).
export type LlmOpsFleetRow = {
  tenant_id: string;
  tenant_name: string;
  total_cost_usd: number;
  request_count: number;
  avg_latency_ms: number;
  // 0..1; rendered as percentage. error_rate > 0.05 surfaces in
  // red text per the two-tier highlighting decision.
  error_rate: number;
  input_tokens_total: number;
  output_tokens_total: number;
  models_used: LlmOpsModel[];
};

export type LlmOpsFleetResponse = { items: LlmOpsFleetRow[] };

// Per-model breakdown row on the detail page. by_request_type
// aggregates further so Anjali sees which request type dominates
// each model's usage.
export type LlmOpsModelStats = {
  model: LlmOpsModel;
  request_count: number;
  total_cost_usd: number;
  avg_latency_ms: number;
  error_rate: number;
  by_request_type: { request_type: LlmOpsRequestType; request_count: number }[];
};

export type LlmOpsTenantDetail = {
  tenant_id: string;
  tenant_name: string;
  total_cost_usd: number;
  request_count: number;
  avg_latency_ms: number;
  error_rate: number;
  models: LlmOpsModelStats[];
  // Last 10 failures across all models, sorted by occurred_at desc.
  recent_failures: LlmOpsRequestEntry[];
};

// Phase 5e.10a: DIS provisioning types retired alongside the
// /dis/admin/provisioning surface. Tenant lifecycle (creation,
// suspension, termination) is platform-superadmin scope; the
// module-side replica duplicated platform authority and is gone.
// 5e.10b reintroduces a leaner DisLifecycleState enum for the
// operational dashboard's state chip — explicit field on tenants.json
// rather than a synthesized provisioning row.

// Phase 5e.10b: DIS operational dashboard (per-tenant view).
//
// Replaces the 5c.8e1 transaction-focused dashboard. Read-only
// surface backed by the existing operational fixtures (streams,
// runs, freshness, alert-events). Time window is implicit per KPI
// (Runs 24h is fixed; Freshness + Alerts are current state); no
// 24h/7d/30d selector.
//
// Personas:
//   PLATFORM (Anjali) — full 7-tenant selector + URL-param override
//   TENANT (Kowalski) — auto-locked to JWT tenant_id claim

export type DisLifecycleState =
  | "NEW"
  | "ONBOARDING"
  | "ACTIVE"
  | "SUSPENDED"
  | "TERMINATED";

export type DisDashboardKpis = {
  state: DisLifecycleState;
  // Floor of (now - tenant.dis_enabled_at), in whole days.
  days_since_enabled: number;
  // Streams: count by lifecycle_state (status field on Stream).
  streams_active_count: number;
  streams_total_count: number;
  // Domain breakdown for active streams; sorted desc by count, tie
  // broken by domain name asc. Rendered compactly in KPI subtext:
  // "2 sales · 1 inventory · 1 customers".
  streams_by_domain: Array<{ domain: string; count: number }>;
  // Runs in last 24h: status breakdown.
  runs_24h_total: number;
  runs_24h_succeeded: number;
  runs_24h_failed: number;
  // Success rate 0..100 (integer). null when runs_24h_total === 0.
  runs_24h_success_rate: number | null;
  // Freshness: % of tenant streams meeting SLO (current_state ===
  // FRESH). 0..100 integer. null when no freshness records.
  freshness_slo_pct: number | null;
  freshness_total_streams: number;
  freshness_stale_or_delayed: number;
  // Open alerts: state IN (UNRESOLVED, ACKNOWLEDGED).
  alerts_open_count: number;
  alerts_by_severity: Array<{ severity: "CRITICAL" | "WARNING" | "INFO"; count: number }>;
};

export type DisDashboardRecentRun = {
  id: string;
  stream_name: string;
  // Filtered to non-null at the handler before reaching the table.
  started_at: string;
  // null when status is non-terminal (QUEUED / RUNNING).
  duration_ms: number | null;
  status: RunStatus;
  // null when status is non-terminal.
  rows_ingested: number | null;
};

export type DisDashboardResponse = {
  tenant_id: string;
  tenant_name: string;
  kpis: DisDashboardKpis;
  // Top 10 runs across all tenant streams, sorted by started_at desc.
  recent_runs: DisDashboardRecentRun[];
};

// Phase 5c.8e2: Cost view + budget editor (PLATFORM-only).
//
// Per-tenant LLM cost vs monthly budget. Spend reads month-to-
// date sums of LLM_OPS_REQUESTS.cost_usd per tenant_id; budget
// reads from cost-budget-store. Status thresholds:
//   UNDER    < 80%  (green)
//   AT_RISK  80-100% (amber) — actionable demo narrative
//   OVER     > 100% (red)

export type BudgetStatus = "UNDER" | "AT_RISK" | "OVER";

export type CostBudgetEntry = {
  tenant_id: string;
  monthly_budget_usd: number;
  last_set_at: string;
  last_set_by_user_id: string;
};

export type CostFleetRow = {
  tenant_id: string;
  tenant_name: string;
  // Sum of LLM_OPS_REQUESTS.cost_usd for this tenant since the
  // start of the current calendar month.
  current_spend_usd: number;
  // Null when no budget is set (neither pre-seed nor user-set).
  // UI renders "Not set" + Edit button still works.
  monthly_budget_usd: number | null;
  // 0..1 fraction of budget consumed. Null when budget is null.
  pct_consumed: number | null;
  // Null when budget is null (status undefined without budget).
  status: BudgetStatus | null;
};

export type CostFleetResponse = { items: CostFleetRow[] };

export type SetBudgetInput = {
  monthly_budget_usd: number;
};

// Phase 5e.7a: DIS Onboarding wizard types removed alongside the
// /dis/onboarding wizard surface retirement. The wizard captured
// intent that never became a real source (no payload consumer
// downstream); first-time tenants discover via "Add source" + the
// sources-list emptiness pattern instead.

// Phase 5c.8f2: system status read surface (informational hub
// alongside docs + changelog). MSW-served; demo audience reads
// it as a production status page. V1 ships all-green; the chip
// vocabulary supports degraded / outage for future incidents.
//
// Phase 5e.4c: renamed from SystemStatus → ServiceStatus to free up
// the SystemStatus name for the Source-the-system identity status
// (which used to be SourceStatus pre-Source/Stream split). Service
// status describes DIS *service* operational health (operational /
// degraded / outage); SystemStatus now describes a Source's system
// identity status (credentials valid / paused / etc.).

export type ServiceStatus = "OPERATIONAL" | "DEGRADED" | "OUTAGE";

export type ServiceStatusEntry = {
  id: string;
  name: string;
  description: string;
  status: ServiceStatus;
};

export type ServiceStatusResponse = {
  entries: ServiceStatusEntry[];
  // ISO timestamp the snapshot was generated. Page renders as
  // "Last updated <relative>" caption.
  generated_at: string;
};

// Phase 5c.8f2: product-narrative changelog. 7 curated milestones
// covering the Phase 5a → 5c arc. Static fixture; MSW-served for
// pattern parity with the rest of DIS.

export type ChangelogTag = "Released" | "Beta" | "Internal";

export type ChangelogEntry = {
  id: string;
  date: string; // ISO date; rendered as YYYY-MM-DD in the timeline column.
  phase: string; // e.g., "Phase 5c.8f1" — labels the technical milestone.
  headline: string;
  // 1-3 short bullets summarizing what shipped from a product
  // perspective (not a git-log dump).
  summary: string[];
  tag: ChangelogTag;
};

export type ChangelogResponse = {
  entries: ChangelogEntry[];
};
