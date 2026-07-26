import type { LocaleDeclaration } from '../../components/locale-rules'
import { parseCsvFile } from '../onboarding/analyze-csv'
import { postJson } from './client'
import { isRealMode } from './mode'
import { getMappingSuggestions } from './mapping-suggestions'
import type { CatalogField, FieldDatatype, TemplateMappingField } from './mapping-fields'

// =====================================================================================
// Connect-a-source CSV branch. The POS/native-connector branch (the PosWizard stubs:
// initiate/exchange OAuth, locations, POS mapping-suggestions, preview, create) was RETIRED
// with PosWizard in S3 — the Square connector now has its own real journey
// (routes/connect/square + lib/dis-ui-server/square-oauth.ts). What remains here is the CSV
// wizard's REAL, deployed-endpoint path plus the mapping-suggestion shapes it shares:
//   - analyzeCsvSample: client-side parse (papaparse, analyze-csv.ts) + POST /mapping-suggestions
//     (type-aware, D90) for per-column targets/confidence/reasoning.
//   - createCsvTemplate / validateCsvTemplate: POST /mapping-templates[/validate] with the
//     Slice-16a semantic columns[] shape (D89).
// =====================================================================================

// ----- AI mapping suggestions (shapes shared by the CSV mapping step) -----------------

export type ConnectorMappingSource = 'vertex' | 'fallback'

// One source field's suggestion, shaped like the real mapping-suggestion response (suggested
// target + alternatives), enriched with the per-row signals the surface shows.
export type ConnectorMappingField = {
  sourceField: string
  // Canonical catalog key, or null. Mirrors MappingSuggestionResponse.Suggestion.suggested_target.
  suggestedTarget: string | null
  // Catalog keys, mirrors Suggestion.alternatives.
  alternatives: string[]
  // Vertex mapping-suggestion confidence (0..1).
  confidence: number
  // Vertex mapping-suggestion reasoning ("why" line).
  reasoning: string | null
  // Detected FORMAT line. Reuses the EXISTING locale/format mechanism (LocaleDeclaration), not a
  // new detected-format API. null = no locale rule applies to this field's datatype (declared
  // client-side in the mapping step).
  detectedFormat: LocaleDeclaration | null
  // A couple of sample values for context.
  sampleValues: string[]
}

export type ConnectorMappingResponse = {
  // Mirrors MappingSuggestionResponse.source ("llm"/"fallback"); "vertex" is the LLM-path label.
  source: ConnectorMappingSource
  fields: ConnectorMappingField[]
}

// =====================================================================================
// CSV branch. The canonical TARGETS for the mapping step are fetched FOR REAL via
// template-mapping-fields?template_type=X (mapping-fields.ts); the analysis, create, and
// validate below are REAL, mode-aware calls to deployed endpoints.
// =====================================================================================

// REAL (D90): parse the uploaded file client-side (papaparse, analyze-csv.ts) into a column
// profile, then call the type-aware /mapping-suggestions endpoint PASSING `template_type` so
// the suggested targets come from the SAME per-type catalog the mapping step's dropdown uses.
// `detectedFormat` is null on purpose: the server returns no format, so the operator DECLARES
// it in the mapping step (locale picker + per-column datetime format), which createCsvTemplate
// assembles into the 16a `src_*` declarations. `catalog` is used ONLY by the fixture-mode
// mechanical matcher (real mode ignores it and the server reads its own per-type catalog).
export async function analyzeCsvSample(
  file: File,
  templateType: string,
  catalog: CatalogField[],
): Promise<ConnectorMappingResponse> {
  const parsed = await parseCsvFile(file)
  // Adapt the type-aware CatalogField[] to the legacy TemplateMappingField shape the fixture
  // matcher reads, dropping the __ignore__/system sentinel (datatype null). The matcher scores
  // on key/display_name/datatype only; section is irrelevant, so the cast is safe.
  const fixtureCatalog: TemplateMappingField[] = catalog
    .filter((f) => f.section !== 'system' && f.key !== '__ignore__' && f.datatype !== null)
    .map((f) => ({
      key: f.key,
      display_name: f.display_name,
      section: f.section as TemplateMappingField['section'],
      mandatory: f.mandatory,
      datatype: f.datatype as FieldDatatype,
      description: f.description,
      allowed_values: f.allowed_values ?? undefined,
      max_length: f.max_length ?? undefined,
    }))
  const resp = await getMappingSuggestions(
    { columns: parsed.columns, template_type: templateType },
    fixtureCatalog,
  )
  const byColumn = new Map(parsed.columns.map((c) => [c.name, c]))
  const fields: ConnectorMappingField[] = resp.suggestions.map((s) => ({
    sourceField: s.source_column,
    suggestedTarget: s.suggested_target,
    alternatives: s.alternatives ?? [],
    confidence: s.confidence,
    reasoning: s.reasoning ?? null,
    detectedFormat: null, // server returns no format; declared client-side (locale picker)
    sampleValues: byColumn.get(s.source_column)?.sample_values ?? [],
  }))
  // MappingSuggestionResponse.source is "llm"/"fallback"; map "llm" -> the surface's "vertex".
  return { source: resp.source === 'llm' ? 'vertex' : 'fallback', fields }
}

// ----- Locale picker (build-ahead, full target set) -----------------------------------
// US / EU / Swiss decimal+thousand presets. KNOWN GAP: as shipped in 16a, the create endpoint
// accepts src_thousand_separator ONLY in {",", "'"} (NOT "."), so the EU dot-thousands preset
// 422s until Sanjeev's 16b. We build the picker for ALL THREE locales anyway (per the brief);
// the type below intentionally allows "." so the EU preset compiles and is offered.
export type LocaleKey = 'us' | 'eu' | 'swiss'
export type LocalePreset = {
  key: LocaleKey
  label: string
  decimal: '.' | ','
  thousand: '.' | ',' | "'"
}
export const LOCALE_PRESETS: LocalePreset[] = [
  { key: 'us', label: 'US (1,299.50)', decimal: '.', thousand: ',' },
  { key: 'eu', label: 'EU (1.299,50)', decimal: ',', thousand: '.' }, // thousand "." 422s until 16b
  { key: 'swiss', label: "Swiss (1'299.50)", decimal: '.', thousand: "'" },
]
export function localePreset(key: LocaleKey): LocalePreset {
  return LOCALE_PRESETS.find((p) => p.key === key) ?? LOCALE_PRESETS[0]
}

// Per-datetime-column format choices. The `value` is the wire token sent verbatim as
// src_datetime_format in the create columns[] body (a READABLE token, never a strptime code):
// Sanjeev's slice-16c translation layer converts the token to the engine format and REJECTS
// any token outside the locked five with a 4xx. This set is held in EXACT lockstep with that
// backend set (DD-MM-YYYY, DD/MM/YYYY, MM/DD/YYYY, YYYY-MM-DD, DD-MM-YY); labels are friendly,
// only the value is load-bearing.
export const CSV_DATETIME_FORMATS: { value: string; label: string }[] = [
  { value: 'DD-MM-YYYY', label: 'Day-Month-Year (31-12-2025)' },
  { value: 'DD/MM/YYYY', label: 'Day/Month/Year (31/12/2025)' },
  { value: 'MM/DD/YYYY', label: 'Month/Day/Year (12/31/2025)' },
  { value: 'YYYY-MM-DD', label: 'Year-Month-Day (2025-12-31)' },
  { value: 'DD-MM-YY', label: 'Day-Month-Year, 2-digit year (31-12-25)' },
]

// ----- Create (Slice-16a semantic columns[] contract, D89) ----------------------------

// One source-to-destination column declaration, mirroring the backend MappingColumn (16a).
// src_thousand_separator allows "." (the EU preset) even though 16a only accepts {",", "'"};
// EU dot-thousands therefore 422s until 16b (deliberate, see LOCALE_PRESETS).
export type ConnectorColumn = {
  src_key: string
  dest_key: string // catalog key for the chosen template_type, or "__ignore__"
  src_datetime_format?: string | null
  src_decimal_separator?: '.' | ',' | null
  src_thousand_separator?: '.' | ',' | "'" | null
  src_is_percentage?: boolean | null
}

export type CreateCsvTemplateInput = {
  // PROVISIONAL: slugified from the source name as a stopgap (collision/quality risk); a
  // dedicated source_id field or a source registry comes later.
  sourceId: string
  templateName: string
  templateType: string
  columns: ConnectorColumn[]
}

// The synthetic-201 reality (16a): a real fresh template_id but NOTHING persisted, no rules
// assembled (draft v1, no active, mapping_version_id 0) until 16c. We read the response
// gracefully - never hard-assume active_version - so the Created UI can be honest.
export type CreatedTemplate = {
  templateId: string
  templateName: string
  templateType: string
  activeVersion: number | null
  draftVersion: number | null
}

type RawCreateResponse = {
  template_id: string
  template_name: string
  template_type: string
  active_version: number | null
  draft_version: number | null
}

// The ONE create/validate wire body (Slice-16a semantic columns[] contract, D89). Both the create
// POST and the validate dry-run POST send EXACTLY this shape, so the dry-run validates the same
// document create would submit — no divergent hand-built body.
function toCreateBody(input: CreateCsvTemplateInput): Record<string, unknown> {
  return {
    source_id: input.sourceId,
    template_name: input.templateName,
    template_type: input.templateType,
    columns: input.columns,
  }
}

// REAL (D89): POST /api/v1/mapping-templates with the semantic columns[] body (NO mapping_rules
// - it is extra-forbidden and would 422). 16a shape-validates + returns a SYNTHETIC 201. Fixture
// mode mirrors that synthetic shape (draft v1, no active). The create persists nothing until
// 16c, so callers must present the result honestly (submitted, not live/listable/ingestible).
export async function createCsvTemplate(input: CreateCsvTemplateInput): Promise<CreatedTemplate> {
  if (isRealMode()) {
    const raw = await postJson<RawCreateResponse>('/api/v1/mapping-templates', toCreateBody(input))
    return {
      templateId: raw.template_id,
      templateName: raw.template_name,
      templateType: raw.template_type,
      activeVersion: raw.active_version,
      draftVersion: raw.draft_version,
    }
  }
  // Fixture: mirror the slice-16c REAL create (create-as-ACTIVE, D88): the row is written ACTIVE
  // and persisted, so the response carries active_version 1 (no draft). Keeps dev/tests in step
  // with real behavior, so CsvCreatedStep shows "Created and live" consistently.
  return {
    templateId: 'tmpl_stub_csv',
    templateName: input.templateName,
    templateType: input.templateType,
    activeVersion: 1,
    draftVersion: null,
  }
}

// Dry-run validate (POST /api/v1/mapping-templates/validate): runs the SAME pure gate create runs
// and returns 200 {valid:true} or the SAME 400 envelope create raises — NO persistence. Sends the
// SAME body as createCsvTemplate (toCreateBody), so validate and create submit identical documents.
// On a non-2xx, postJson throws DisUiServerHttpError (the shared envelope parser create errors use);
// the caller (runBackendDryRun) maps that verbatim shape into ValidationIssue[]. Fixture mode has no
// backend, so it resolves as a no-op (the client-side checks + Activate stub stand alone there).
export async function validateCsvTemplate(input: CreateCsvTemplateInput): Promise<void> {
  if (!isRealMode()) return
  await postJson<{ valid: boolean }>('/api/v1/mapping-templates/validate', toCreateBody(input))
}

// TODO(wire): the client-side preview shape is not re-confirmed for this surface. The real flow
// would coerce the parsed sample rows through the assembled mapping (the server pipeline is the
// authoritative coercion). This stub returns fixed canonical-keyed rows; the surface drops
// ignored targets before rendering.
export function fetchCsvPreviewRows(): Promise<Record<string, string>[]> {
  return Promise.resolve([
    {
      sku_id: 'TSHIRT-RED-M',
      quantity: '2',
      unit_sale_price: '1299.50',
      source_sale_timestamp: '2025-12-31T00:00:00+00:00',
      transaction_id: 'R-1001',
      event_subtype: 'SALE',
    },
    {
      sku_id: 'MUG-001',
      quantity: '1',
      unit_sale_price: '19.00',
      source_sale_timestamp: '2026-01-01T00:00:00+00:00',
      transaction_id: 'R-1002',
      event_subtype: 'RETURN',
    },
  ])
}
