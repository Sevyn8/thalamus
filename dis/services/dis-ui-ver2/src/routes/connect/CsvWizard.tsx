import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { FileDropzone } from '../../components/FileDropzone'
import { ErrorState } from '../../components/states/ErrorState'
import { LoadingState } from '../../components/states/LoadingState'
import {
  analyzeCsvSample,
  createCsvTemplate,
  localePreset,
} from '../../lib/dis-ui-server/connectors-api'
import type {
  ConnectorMappingField,
  ConnectorMappingResponse,
  ConnectorMappingSource,
  CreatedTemplate,
  CreateCsvTemplateInput,
  LocaleKey,
} from '../../lib/dis-ui-server/connectors-api'
import type { CatalogField } from '../../lib/dis-ui-server/mapping-fields'
import { useTemplateMappingFieldsForType } from '../../lib/dis-ui-server/mapping-fields'
import type { MappingRow, ValidationIssue } from '../../lib/dis-ui-server/mapping-validation'
import { runBackendDryRun, runClientSideChecks } from '../../lib/dis-ui-server/mapping-validation'
import { createSourceIfAbsent } from '../../lib/dis-ui-server/sources'
import { useTemplateTypes } from '../../lib/dis-ui-server/template-types'
import { StepRail } from './StepRail'
import type { RailStep } from './StepRail'

// CSV wizard, mockup-shaped (connect-source.html rail minus Configure/Test — a file upload has
// no connection). 7 steps: Source & method -> Upload sample -> Parsing profile -> Data type ->
// AI mapping -> Preview -> Activate. Logic donor: dis-ui's CSV branch, but the surface follows
// the mockup. REAL, mode-aware calls: useTemplateTypes (GET /template-types),
// useTemplateMappingFieldsForType (GET /template-mapping-fields), analyzeCsvSample (client
// papaparse -> getMappingSuggestions POST /mapping-suggestions, Gemini->canonical),
// createCsvTemplate (POST /api/v1/mapping-templates).

const STEPS: RailStep[] = [
  { title: 'Source & method', desc: 'Manual CSV upload' },
  { title: 'Upload sample', desc: 'A CSV to read its columns' },
  { title: 'Parsing profile', desc: 'Locale & formats' },
  { title: 'Data type', desc: 'What this represents' },
  { title: 'AI mapping', desc: 'Source to canonical' },
  { title: 'Preview', desc: 'Validate before activation' },
  { title: 'Activate', desc: 'Create the template' },
]
const LOCALES: { key: LocaleKey; label: string }[] = [
  { key: 'us', label: 'US (1,234.56)' },
  { key: 'eu', label: 'EU (1.234,56)' },
  { key: 'swiss', label: "Swiss (1'234.56)" },
]

// Human-readable section labels for the canonical-target dropdown (mirrors v1 MappingStep);
// unknown sections humanize their key. `system` (the __ignore__ sentinel) is never an option —
// Ignore is the per-row checkbox instead.
const SECTION_LABEL: Record<string, string> = {
  sale_event: 'Sale event',
  change_event: 'Change event',
  identity: 'Identity',
  product: 'Product',
  pricing: 'Pricing',
  inventory: 'Inventory',
  expiry: 'Expiry',
  regulatory_status: 'Regulatory status',
}

function humanizeSection(section: string): string {
  return SECTION_LABEL[section] ?? section.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
}

// Section-grouped canonical target <optgroup>s built from the type-aware catalog (the SAME
// catalog GET /template-mapping-fields?template_type= serves, already loaded in the wizard).
// Excludes the `system`/`__ignore__` sentinel (Ignore is the row checkbox). display + ` *` when
// mandatory + ` (datatype)`, matching v1.
function canonicalOptionGroups(catalog: CatalogField[]) {
  const sections: string[] = []
  for (const f of catalog) {
    if (f.section !== 'system' && f.key !== '__ignore__' && !sections.includes(f.section)) {
      sections.push(f.section)
    }
  }
  return sections.map((section) => (
    <optgroup key={section} label={humanizeSection(section)}>
      {catalog
        .filter((f) => f.section === section && f.key !== '__ignore__')
        .map((f) => (
          <option key={`${section}-${f.key}`} value={f.key}>
            {f.display_name}
            {f.mandatory ? ' *' : ''}
            {f.datatype !== null ? ` (${f.datatype})` : ''}
          </option>
        ))}
    </optgroup>
  ))
}

// Short, row-anchored copy for an inline danger message, keyed by the issue id. Falls back to the
// issue's panel message for any id we do not have bespoke row copy for (e.g. a future dry-run
// issue), so the inline surface needs no change when new issue kinds arrive.
const ROW_MESSAGE: Record<string, string> = {
  'unique-targets': 'This field is mapped by more than one column — change or ignore one.',
  'columns-resolved': 'Not mapped yet — pick a target or tick Ignore.',
}
function rowMessageFor(issue: ValidationIssue): string {
  return ROW_MESSAGE[issue.id] ?? issue.message
}

// Confidence -> a High/Medium/Low chip in a v2 semantic tone (presentation only).
function confidenceBand(confidence: number): { text: string; cls: string } {
  if (confidence >= 0.8) return { text: 'High', cls: 'b-ok' }
  if (confidence >= 0.5) return { text: 'Medium', cls: 'b-warn' }
  return { text: 'Low', cls: 'b-fail' }
}

// The target a field STARTS at before the operator edits it. CORRECTNESS (Item 2a): the mechanical
// fallback matcher returns the argmax catalog field for EVERY column, even with no real name match
// (confidence 0.0 — e.g. it defaults every unmatched column to the first catalog field, "event_date").
// That defaulted guess is NOT a real suggestion, so we seed it as Unmapped ('') instead of
// pre-selecting a confident-looking target. Combined with the step-4 gating (no activate while a
// non-ignored field is unmapped), this prevents persisting a garbage all-defaulted mapping.
// A >0%-confidence fallback match (a real name hit) still pre-fills as a low-confidence guess.
function seedTarget(f: ConnectorMappingField, source: ConnectorMappingSource): string {
  if (source === 'fallback' && f.confidence === 0) return ''
  return f.suggestedTarget ?? ''
}

export function CsvWizard({ onBack }: { onBack: () => void }) {
  const [step, setStep] = useState(1) // Source&method (0) already chosen
  const [file, setFile] = useState<File | null>(null)
  const [sourceName, setSourceName] = useState('')
  const [locale, setLocale] = useState<LocaleKey>('us')
  const [templateType, setTemplateType] = useState('')
  const [created, setCreated] = useState<CreatedTemplate | null>(null)
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  // Human-approved mapping edits (wizard-scoped; mirrors v1 connector-setup state). The suggestion
  // set itself stays in the analysis query; these hold ONLY the operator's decisions.
  //   mappingOverrides: sourceField -> chosen canonical key (absent => use the suggestion's target)
  //   ignored:          sourceField -> excluded from the template (assigned to __ignore__)
  // DEFERRED: per-column source-format declarations (v1's csvColumnFormat/locale) are NOT collected
  // here yet — the create body omits src_datetime_format/src_decimal_separator/src_is_percentage,
  // exactly as this wizard did before. That is a separate follow-up, out of scope for this build.
  const [mappingOverrides, setMappingOverrides] = useState<Record<string, string>>({})
  const [ignored, setIgnored] = useState<Record<string, boolean>>({})
  // Backend dry-run state (companion-group validation at the Continue step). Issues BLOCK Continue;
  // the soft note (transport/persona) does NOT — it lets Continue proceed with Activate as backstop.
  //   dryRunIssues — mapped from a 400 envelope (real gate failures); merged into the panel/inline.
  //   dryRunNote   — a soft, non-blocking note when the dry-run could not authoritatively run.
  //   dryRunPending — request in flight (panel shows a pending row; Continue disabled to avoid re-fire).
  //   dryRunSoftFailed — a transport/persona failure already happened for THIS mapping, so the next
  //     Continue press proceeds without re-calling (no retry loop). All three clear on any edit.
  const [dryRunIssues, setDryRunIssues] = useState<ValidationIssue[]>([])
  const [dryRunNote, setDryRunNote] = useState<string | null>(null)
  const [dryRunPending, setDryRunPending] = useState(false)
  const [dryRunSoftFailed, setDryRunSoftFailed] = useState(false)
  // Any mapping edit makes a prior dry-run result STALE: clear it so the gate falls back to the
  // live client-side checks until the next Continue press re-validates.
  const clearDryRun = (): void => {
    setDryRunIssues([])
    setDryRunNote(null)
    setDryRunSoftFailed(false)
  }
  const mappingTargetFor = (f: ConnectorMappingField, source: ConnectorMappingSource): string =>
    mappingOverrides[f.sourceField] ?? seedTarget(f, source)
  const isIgnored = (sourceField: string): boolean => ignored[sourceField] ?? false
  const setTarget = (sourceField: string, target: string): void => {
    clearDryRun()
    setMappingOverrides((prev) => ({ ...prev, [sourceField]: target }))
  }
  const toggleIgnore = (sourceField: string): void => {
    clearDryRun()
    setIgnored((prev) => ({ ...prev, [sourceField]: !(prev[sourceField] ?? false) }))
  }

  const types = useTemplateTypes()
  const fields = useTemplateMappingFieldsForType(templateType || null)
  const catalog: CatalogField[] = fields.data ?? []

  // Real analysis: papaparse the file, then Gemini->canonical suggestions. Runs once we reach
  // the mapping step with a file + chosen type + loaded catalog.
  const analysis = useQuery<ConnectorMappingResponse>({
    queryKey: ['connect-csv-analyze', file?.name ?? '', templateType],
    queryFn: () => analyzeCsvSample(file as File, templateType, catalog),
    enabled: step >= 4 && file !== null && templateType !== '' && catalog.length > 0,
    retry: false,
    // Fire /mapping-suggestions (an LLM round-trip that hits Vertex) EXACTLY ONCE per mapping step.
    // Without these, react-query's default refetchOnWindowFocus/Mount/Reconnect re-fired the POST
    // mid-call (a tab blur→focus during the slow call), doubling the Vertex rate → 429s. staleTime
    // Infinity matches the lib clients' convention; refetchOnWindowFocus:false is belt-and-suspenders.
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  })
  // The producer that made the current suggestions ('vertex' = LLM, 'fallback' = mechanical). Drives
  // the fallback banner + the 0%-confidence seed rule (Item 2a/2b). Defaults conservatively to
  // 'fallback' before data lands (case 4 only renders once data is present).
  const suggestionSource: ConnectorMappingSource = analysis.data?.source ?? 'fallback'

  // Mapping-step validation (the "Continue" gate). Client-side checks only, re-run on EVERY render
  // so the checklist panel + inline row state update live as the operator edits targets / ignores.
  // The mapping the wizard holds -> the shared ValidationIssue model (see mapping-validation.ts).
  const validationRows: MappingRow[] = (analysis.data?.fields ?? []).map((f) => ({
    sourceField: f.sourceField,
    target: mappingTargetFor(f, suggestionSource),
    ignored: isIgnored(f.sourceField),
  }))
  const clientIssues = runClientSideChecks(validationRows, catalog)
  // Combined issues = live client-side checks + any backend dry-run issues (companion-group
  // pairings) discovered on the last Continue press. Both block Continue and render in the same
  // panel/inline; dry-run issues clear on any edit (staleness), re-checked on the next press.
  const issues: ValidationIssue[] = [...clientIssues, ...dryRunIssues]
  const mappingValid = analysis.data !== undefined && issues.length === 0

  const jump = (i: number) => setStep(i)
  const next = () => setStep((s) => Math.min(s + 1, STEPS.length - 1))
  const back = () => setStep((s) => (s <= 1 ? (onBack(), 0) : s - 1))

  // The SINGLE source of the create/validate body: the human-edited mapping (ignored -> __ignore__,
  // else the chosen target). Both the dry-run (Continue) and the create (Activate) build from this,
  // so validate and create submit identical documents.
  function buildCreateInput(): CreateCsvTemplateInput {
    const columns = (analysis.data?.fields ?? []).map((f) => ({
      src_key: f.sourceField,
      dest_key: isIgnored(f.sourceField) ? '__ignore__' : mappingTargetFor(f, suggestionSource),
    }))
    const sourceId = (sourceName || 'manual_csv_upload').toLowerCase().replace(/[^a-z0-9_]+/g, '_')
    return { sourceId, templateName: sourceName || 'CSV template', templateType, columns }
  }

  // The mapping-step Continue gate. Client-side checks already gate the button; on press we run the
  // backend dry-run (the ONE endpoint hit — not per-keystroke, so the tenant-scoped validate call is
  // not spammed) for the companion-group rules the frontend cannot know. A 400 blocks with the real
  // issue; a clean pass advances; a transport/persona failure notes softly and lets the next press
  // proceed (Activate is the backstop). Already soft-failed for this mapping -> proceed without re-firing.
  async function continueFromMapping(): Promise<void> {
    if (dryRunSoftFailed) {
      next()
      return
    }
    setDryRunNote(null)
    setDryRunPending(true)
    try {
      const outcome = await runBackendDryRun(buildCreateInput())
      if (outcome.status === 'ok') {
        if (outcome.issues.length === 0) {
          setDryRunIssues([])
          next()
        } else {
          setDryRunIssues(outcome.issues) // real gate failure -> block, render in the panel
        }
      } else if (outcome.status === 'forbidden') {
        // Wrong persona for a tenant-scoped mapping (like the create 403), NOT a mapping issue.
        setDryRunNote("This mapping is validated as its tenant — your role can't validate it here. Activate will report the same.")
        setDryRunSoftFailed(true)
      } else {
        // Transport/5xx: do not claim valid or invalid; proceed, Activate catches any real error.
        setDryRunNote("Couldn't reach validation — we'll check it when you activate.")
        setDryRunSoftFailed(true)
      }
    } finally {
      setDryRunPending(false)
    }
  }

  async function activate(): Promise<void> {
    setCreateError(null)
    setCreating(true)
    try {
      // Persist the HUMAN-EDITED mapping via the SAME builder the dry-run used (identical body).
      const input = buildCreateInput()
      // Source-first (D112): register the source entity (channel csv_upload — this IS the manual
      // CSV path), tolerating a 409 if it already exists (a prior run, or the 0013 backfill). Any
      // other error surfaces (createSourceIfAbsent re-throws it). Then create the mapping template.
      await createSourceIfAbsent({
        source_id: input.sourceId,
        display_name: sourceName || input.sourceId,
        channel: 'csv_upload',
      })
      const result = await createCsvTemplate(input)
      setCreated(result)
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : 'Create failed.')
    } finally {
      setCreating(false)
    }
  }

  // Mapping-step validation panel: issue-count framing (not "N of M checks passing"). Each failing
  // issue is NAMED BY CLASS (Required / Duplicate / Unmapped client-side; Dependent from the server
  // dry-run) with specifics-first copy + the exact action. Recomputes every render. Dependent issues
  // only appear AFTER a Continue-press dry-run returns a companion-group 400 — never a pre-check
  // placeholder (that check hasn't run until Continue).
  function validationPanel() {
    const count = issues.length
    return (
      <div className="valpanel" role="status" aria-label="Mapping checks">
        <div className="valhd">
          <b>{count === 0 ? 'All checks passing' : `${count} issue${count === 1 ? '' : 's'} to fix before continuing`}</b>
          <span className="hint">Continue runs a full server check.</span>
        </div>
        {dryRunPending ? <LoadingState label="Checking with the server…" /> : null}
        {dryRunNote !== null ? (
          <div className="valnote" role="note">
            {dryRunNote}
          </div>
        ) : null}
        {issues.map((issue) => (
          <div key={issue.id} className="valrow">
            <span className="badge b-fail">{issue.classLabel}</span>
            <div className="valtext">
              <span className="valmsg">{issue.message}</span>
            </div>
          </div>
        ))}
      </div>
    )
  }

  function panel() {
    switch (step) {
      case 1:
        return (
          <div className="field">
            <label htmlFor="csv-name">Source name</label>
            <input
              id="csv-name"
              className="input"
              value={sourceName}
              onChange={(e) => setSourceName(e.target.value)}
              placeholder="e.g. Weekly sales export"
            />
            <div style={{ marginTop: 14 }}>
              <FileDropzone
                id="connect-csv-file"
                label="Sample CSV"
                file={file}
                onSelect={setFile}
                accept=".csv"
                hint="CSV up to 10 MB"
              />
            </div>
          </div>
        )
      case 2:
        return (
          <div className="field">
            <fieldset className="locradio">
              <legend>Number & date locale</legend>
              {LOCALES.map((l) => (
                <label key={l.key} className={`locopt ${locale === l.key ? 'on' : ''}`}>
                  <input
                    type="radio"
                    name="csv-locale"
                    value={l.key}
                    checked={locale === l.key}
                    onChange={() => setLocale(l.key)}
                  />
                  <span>{l.label}</span>
                </label>
              ))}
            </fieldset>
            <span className="hint">
              Decimal “{localePreset(locale).decimal}”, thousands “{localePreset(locale).thousand}”.
            </span>
          </div>
        )
      case 3:
        return types.isPending ? (
          <LoadingState label="Loading template types…" />
        ) : (
          <div className="choicegrid">
            {(types.data ?? []).map((t) => (
              <button
                key={t.key}
                type="button"
                className={`choice ${templateType === t.key ? 'on' : ''}`}
                onClick={() => setTemplateType(t.key)}
              >
                <div className="t">{t.display_name}</div>
                <div className="d">{t.description}</div>
              </button>
            ))}
          </div>
        )
      case 4:
        // Item 1 — honest loader while the (LLM round-trip) suggestions call is in flight.
        if (analysis.isPending || fields.isPending)
          return <LoadingState label="Analyzing your columns — this can take a few seconds…" />
        if (analysis.isError) return <ErrorState message="Mapping analysis failed." onRetry={() => void analysis.refetch()} />
        return (
          <div className="card">
            <div className="hd">
              <h3>AI mapping</h3>
              {/* honest producer label: llm -> "vertex" surface tag, else the mechanical fallback */}
              <span className={`badge ${suggestionSource === 'vertex' ? 'b-info' : 'b-mut'}`}>
                Suggestions: {suggestionSource === 'vertex' ? 'AI' : 'basic match'}
              </span>
            </div>
            <div className="bd" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {/* Item 2b — honest fallback banner. NO retry button: 'fallback' carries no
                  degrade_reason on the wire, so it can mean Vertex is unconfigured (a retry would
                  loop forever) as easily as a transient error. A reliable "Retry AI" needs a
                  backend degrade_reason field (future ask to Sanjeev; out of scope here). */}
              {suggestionSource === 'fallback' ? (
                <div className="warnbox" role="note">
                  AI mapping is unavailable right now — review the columns and set each target
                  manually.
                </div>
              ) : null}
              <p className="hint" style={{ margin: 0 }}>
                Review each suggestion. Change a target, or ignore a column — what you approve here
                (not the raw suggestion) is what the template is created from.
              </p>
              {validationPanel()}
              {(analysis.data?.fields ?? []).map((f) => {
                const ign = isIgnored(f.sourceField)
                const band = confidenceBand(f.confidence)
                const rowIssue = ign ? undefined : issues.find((i) => (i.offendingRows ?? []).includes(f.sourceField))
                return (
                  <div key={f.sourceField} className={`maprow${ign ? ' ignored' : ''}${rowIssue ? ' invalid' : ''}`}>
                    <div className="maptop">
                      <span className="srcname" title={f.sourceField}>
                        {f.sourceField}
                      </span>
                      <span className="arrow" aria-hidden="true">
                        →
                      </span>
                      <select
                        className="input"
                        aria-label={`Canonical target for ${f.sourceField}`}
                        value={mappingTargetFor(f, suggestionSource)}
                        disabled={ign}
                        onChange={(e) => setTarget(f.sourceField, e.target.value)}
                      >
                        <option value="">Unmapped</option>
                        {f.alternatives.length > 0 ? (
                          <optgroup label="Assistant's alternatives">
                            {f.alternatives.map((alt) => (
                              <option key={`alt-${alt}`} value={alt}>
                                {alt}
                              </option>
                            ))}
                          </optgroup>
                        ) : null}
                        {canonicalOptionGroups(catalog)}
                      </select>
                      {ign ? (
                        <span className="badge b-mut">Ignored</span>
                      ) : (
                        <span className={`badge ${band.cls}`}>
                          {Math.round(f.confidence * 100)}% {band.text}
                        </span>
                      )}
                      <label className="ignchk">
                        <input
                          type="checkbox"
                          aria-label={`Ignore ${f.sourceField}`}
                          checked={ign}
                          onChange={() => toggleIgnore(f.sourceField)}
                        />
                        Ignore
                      </label>
                    </div>
                    {ign ? (
                      <div className="why">Excluded from the template (assigned to __ignore__).</div>
                    ) : rowIssue ? (
                      <div className="rowerr" role="note">
                        {rowMessageFor(rowIssue)}
                      </div>
                    ) : f.reasoning !== null && f.reasoning.length > 0 ? (
                      <div className="why">Why: {f.reasoning}</div>
                    ) : null}
                  </div>
                )
              })}
            </div>
          </div>
        )
      case 5:
        return (
          <div className="card">
            <div className="hd">
              <h3>Preview</h3>
            </div>
            <div className="bd">
              {/* Preview reflects the APPROVED mapping: edited targets, ignored columns dropped. */}
              <dl className="kv">
                {(analysis.data?.fields ?? [])
                  .filter((f) => !isIgnored(f.sourceField) && mappingTargetFor(f, suggestionSource) !== '')
                  .map((f) => (
                    <div key={f.sourceField} style={{ display: 'contents' }}>
                      <dt>{f.sourceField}</dt>
                      <dd className="mono">
                        → {mappingTargetFor(f, suggestionSource)}
                        {f.sampleValues.length ? `  (e.g. ${f.sampleValues[0]})` : ''}
                      </dd>
                    </div>
                  ))}
              </dl>
            </div>
          </div>
        )
      case 6:
        return created !== null ? (
          <div className="okbox" role="status">
            Template created: <b>{created.templateName}</b> ({created.templateId}). New files for
            this source flow through it.
          </div>
        ) : (
          <div className="field">
            <p className="hint" style={{ marginBottom: 12 }}>
              Create the mapping template from the confirmed mapping. This POSTs to
              /api/v1/mapping-templates.
            </p>
            {createError !== null ? (
              <div className="failbox" role="alert" style={{ marginBottom: 12 }}>
                {createError}
              </div>
            ) : null}
            <button
              type="button"
              className="btn pri"
              disabled={creating || (analysis.data?.fields ?? []).length === 0}
              onClick={() => void activate()}
            >
              {creating ? 'Creating…' : 'Activate template'}
            </button>
          </div>
        )
      default:
        return null
    }
  }

  // Step 4 gating: the mapping is approvable only when every client-side check passes (see
  // mappingValid / mapping-validation.ts). Continue enabled here means the CLIENT-SIDE checks pass;
  // it does NOT yet guarantee backend validation (the companion-group pairings are checked at
  // Activate until the dry-run seam is wired).
  // Step 4 stays enabled after a soft dry-run failure (mappingValid still true, issues empty) so the
  // next press can proceed; it is disabled only while the dry-run is in flight.
  const canNext =
    (step === 1 && file !== null) ||
    step === 2 ||
    (step === 3 && templateType !== '') ||
    (step === 4 && mappingValid && !dryRunPending) ||
    step === 5
  // On the mapping step, label Continue with the outstanding issue count so a disabled button
  // reads honestly ("Continue — 2 issues").
  const issueCount = issues.length
  const continueLabel =
    step === 4 && issueCount > 0 ? `Continue — ${issueCount} issue${issueCount > 1 ? 's' : ''}` : 'Continue'

  return (
    <div className="wizwrap">
      <StepRail steps={STEPS} current={step} onJump={(i) => (i === 0 ? onBack() : jump(i))} />
      <div>
        <h2 className="text-lg font-semibold" style={{ marginBottom: 4 }}>
          {STEPS[step].title}
        </h2>
        <p className="sub" style={{ marginBottom: 16 }}>
          {STEPS[step].desc}
        </p>
        {panel()}
        {step < 6 ? (
          <div className="wizfoot">
            <button type="button" className="btn" onClick={back}>
              Back
            </button>
            <button
              type="button"
              className="btn pri"
              disabled={!canNext}
              onClick={step === 4 ? () => void continueFromMapping() : next}
            >
              {continueLabel}
            </button>
          </div>
        ) : null}
      </div>
    </div>
  )
}
