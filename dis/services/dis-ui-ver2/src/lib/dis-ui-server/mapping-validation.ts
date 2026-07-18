import { DisUiServerHttpError } from './client'
import type { CreateCsvTemplateInput } from './connectors-api'
import { validateCsvTemplate } from './connectors-api'
import type { CatalogField } from './mapping-fields'

// Mapping-step validation (CsvWizard "Continue" gate). This validates the mapping the wizard
// HOLDS, at the mapping step, BEFORE Activate. It is deliberately CLIENT-SIDE-ONLY and covers
// exactly the rules that are genuinely frontend-knowable with NO backend rule duplication:
//
//   1. unique-targets     - no two source columns map to the same canonical field. Pure property
//                           of the mapping in hand (two rename entries -> one target).
//   2. required-coverage  - every MANDATORY canonical field for the chosen template_type is
//                           mapped. Reads the `mandatory` flag ALREADY served in the
//                           template-mapping-fields catalog (useTemplateMappingFieldsForType) -
//                           NO hardcoded field list.
//   3. columns-resolved   - every source column is either mapped or explicitly ignored. An
//                           unmapped, non-ignored column would POST an empty dest_key and 422 at
//                           create; this preserves the wizard's prior completeness gate, now made
//                           visible as a check instead of a hidden condition.
//
// DELIBERATELY NOT HERE: the companion-group presence pairings (the expiry triple, the promo
// pair). Those are BACKEND-ONLY rules (they live in dis-ui-server's _CATALOGUE_PRESENCE_PAIRINGS
// / the streaming consumer's HOT_CHECK_IMPLICATIONS / the hot-table CHECK constraints), and their
// group definitions are NOT exposed to the frontend (the catalog's `constraints` field is null in
// v1, and `section` groupings do not encode the pairs). Mirroring them here would duplicate a
// backend rule tuple and drift. They will arrive via the backend dry-run seam below
// (runBackendDryRun) as extra ValidationIssue entries into the SAME model - zero UI rework.

export type ValidationSeverity = 'error' | 'warning'

// The shared validation model. Client-side checks (below) produce these NOW; a future backend
// dry-run produces MORE of these (companion-group errors) into the same list. The panel and the
// inline row highlighting render from this single shape, so wiring the dry-run later is additive.
//
//   id            - stable identifier of the rule (drives panel de-dup + inline row keying)
//   classLabel    - the error CLASS tag shown in the panel: 'Required' / 'Duplicate' / 'Unmapped'
//                   (client-side) or 'Dependent' (backend companion-group). Names the problem class.
//   severity      - 'error' blocks Continue; 'warning' is advisory (none emitted yet)
//   message       - human, panel-facing copy: SPECIFICS first, then the exact action
//   offendingRows - sourceField ids to highlight inline; ABSENT when the issue is not anchored to
//                   a row (e.g. a required field that is simply absent has no row to point at)
export type ValidationIssue = {
  id: string
  classLabel: string
  severity: ValidationSeverity
  message: string
  offendingRows?: string[]
}

// One row of the mapping as the wizard holds it: a source column, its chosen canonical target
// ('' = Unmapped), and whether the operator ignored it.
export type MappingRow = {
  sourceField: string
  target: string
  ignored: boolean
}

const IGNORE_TARGET = '__ignore__'

// The client-side checks, in panel display order. Each id matches the ValidationIssue.id a failing
// check emits, so the panel derives pass/fail per descriptor by presence of an issue with that id.
export const CLIENT_CHECKS: { id: string; label: string }[] = [
  { id: 'required-coverage', label: 'All required fields mapped' },
  { id: 'unique-targets', label: 'Each field used once' },
  { id: 'columns-resolved', label: 'Every column mapped or ignored' },
]

// An "active" row contributes a canonical target: not ignored, and actually mapped.
function isActive(row: MappingRow): boolean {
  return !row.ignored && row.target !== '' && row.target !== IGNORE_TARGET
}

// The catalog field LABEL for a canonical key (falls back to the raw key when the catalog has no
// entry — e.g. in a unit test with no catalog), so messages name fields the way the operator sees.
function labelFor(target: string, catalog?: CatalogField[]): string {
  return catalog?.find((f) => f.key === target)?.display_name ?? target
}

const COUNT_WORD: Record<number, string> = { 2: 'Two', 3: 'Three', 4: 'Four' }
function countWord(n: number): string {
  return COUNT_WORD[n] ?? String(n)
}

// Check 1 — DUPLICATE class: two (or more) source columns mapped to one canonical field. Leads with
// the specific duplicated field(s), then the exact action. Uses catalog labels when available.
export function checkUniqueTargets(rows: MappingRow[], catalog?: CatalogField[]): ValidationIssue | null {
  const sourcesByTarget = new Map<string, string[]>()
  for (const row of rows) {
    if (!isActive(row)) continue
    const sources = sourcesByTarget.get(row.target) ?? []
    sources.push(row.sourceField)
    sourcesByTarget.set(row.target, sources)
  }
  const dupes: { target: string; count: number }[] = []
  const offendingRows: string[] = []
  for (const [target, sources] of sourcesByTarget) {
    if (sources.length > 1) {
      dupes.push({ target, count: sources.length })
      offendingRows.push(...sources)
    }
  }
  if (offendingRows.length === 0) return null
  const phrases = dupes.map((d) => `${countWord(d.count)} columns map to ${labelFor(d.target, catalog)}`)
  return {
    id: 'unique-targets',
    classLabel: 'Duplicate',
    severity: 'error',
    message: `${phrases.join('; ')}. Each field can receive only one column. Change or ignore one.`,
    offendingRows,
  }
}

// Check 2: every mandatory canonical field for the type is mapped. Reads the catalog's `mandatory`
// flag - no hardcoded list. A missing required field is not anchored to a row (nothing maps to it),
// so this issue carries no offendingRows; the panel names the missing field(s) instead.
export function checkRequiredCoverage(rows: MappingRow[], catalog: CatalogField[]): ValidationIssue | null {
  const mappedTargets = new Set(rows.filter(isActive).map((row) => row.target))
  const missing = catalog.filter(
    (field) => field.mandatory && field.key !== IGNORE_TARGET && !mappedTargets.has(field.key),
  )
  if (missing.length === 0) return null
  const n = missing.length
  const names = missing.map((field) => field.display_name).join(', ')
  // REQUIRED class: lead with the count + the specific field labels, then the exact action.
  return {
    id: 'required-coverage',
    classLabel: 'Required',
    severity: 'error',
    message:
      `${n} required field${n === 1 ? '' : 's'} still need${n === 1 ? 's' : ''} a column: ${names}. ` +
      `Map a source column to each. If your file doesn't contain this data, it can't be used with this template.`,
  }
}

// Check 3: every source column is mapped or ignored (no empty dest_key would be sent).
export function checkColumnsResolved(rows: MappingRow[]): ValidationIssue | null {
  const unresolved = rows.filter((row) => !row.ignored && row.target === '')
  if (unresolved.length === 0) return null
  return {
    id: 'columns-resolved',
    classLabel: 'Unmapped',
    severity: 'error',
    message: `Some columns are neither mapped nor ignored. Pick a target for each, or tick Ignore.`,
    offendingRows: unresolved.map((row) => row.sourceField),
  }
}

// Run all client-side checks; returns one issue per failing check (in CLIENT_CHECKS order).
export function runClientSideChecks(rows: MappingRow[], catalog: CatalogField[]): ValidationIssue[] {
  return [
    checkRequiredCoverage(rows, catalog),
    checkUniqueTargets(rows, catalog),
    checkColumnsResolved(rows),
  ].filter((issue): issue is ValidationIssue => issue !== null)
}

// The set of sourceFields that any issue flags, for inline row highlighting.
export function offendingRowSet(issues: ValidationIssue[]): Set<string> {
  return new Set(issues.flatMap((issue) => issue.offendingRows ?? []))
}

// ============================================================================================
// BACKEND DRY-RUN (WIRED): POST /api/v1/mapping-templates/validate.
//
// The companion-group presence pairings (expiry triple, promo pair) are backend-only rules a
// mapping can violate while passing every client-side check above. The dry-run runs the SAME pure
// gate create runs (no persistence) and returns the SAME 400 envelope create raises, so those
// errors surface at the Continue step instead of only at Activate — WITHOUT mirroring the backend
// rules client-side. `validateCsvTemplate` sends the SAME body createCsvTemplate sends (one
// builder), and `postJson` throws `DisUiServerHttpError` on a non-2xx (the shared envelope parser
// the Activate failbox already uses) — so there is ONE parser, reused verbatim.
// ============================================================================================

// The outcome of a dry-run. `ok` means validation AUTHORITATIVELY ran (200 -> issues [], or a 400
// -> the mapped issues). `forbidden` (403) is the WRONG PERSONA for a tenant-scoped mapping, not a
// mapping problem — handled like the create 403, never rendered as a validation issue. `unreachable`
// is any transport/5xx failure — we do NOT claim valid or invalid; the Activate 400 is the backstop.
export type DryRunOutcome =
  | { status: 'ok'; issues: ValidationIssue[] }
  | { status: 'forbidden' }
  | { status: 'unreachable' }

// Map the SAME 400 envelope create raises into a panel issue. The envelope's `details` do NOT name
// the implicated columns (only the human `message` does), so this is a panel-only issue (no
// offendingRows) carrying the backend's verbatim message — no message-parsing, no re-encoding the
// backend pairing rules in TS. The id is namespaced so the panel renders it as an extra line.
// DEPENDENT class: a backend companion-group failure (expiry-triple / promo-pair — all-or-none).
// These are server-checked ONLY (not computed client-side), so this issue exists solely as the
// mapped 400; the panel shows the backend's prose message verbatim under the "Dependent" tag.
function dryRunIssueFrom(err: DisUiServerHttpError): ValidationIssue {
  return {
    id: `backend:${err.code || 'validation'}`,
    classLabel: 'Dependent',
    severity: 'error',
    message: err.message,
  }
}

export async function runBackendDryRun(input: CreateCsvTemplateInput): Promise<DryRunOutcome> {
  try {
    await validateCsvTemplate(input) // 200 {valid:true} (or fixture no-op) resolves; non-2xx throws
    return { status: 'ok', issues: [] }
  } catch (err) {
    if (err instanceof DisUiServerHttpError) {
      // 400 == the SAME gate failure create raises (companion-group pairing etc.): a real issue.
      if (err.status === 400) return { status: 'ok', issues: [dryRunIssueFrom(err)] }
      // 403 == wrong persona (platform / tenant-less) for a tenant-scoped mapping, like create's 403.
      if (err.status === 403) return { status: 'forbidden' }
    }
    // Network / 5xx / anything else: do not fabricate an issue; Activate remains the backstop.
    return { status: 'unreachable' }
  }
}
