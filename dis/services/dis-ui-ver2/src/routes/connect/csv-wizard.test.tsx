import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { writeToken } from '../../auth/storage'
import { CsvWizard } from './CsvWizard'

// The CsvWizard AI-mapping step is now EDITABLE (human-approved LLM mapping): per-field target
// <select> seeded from the suggestion (+ an "Assistant's alternatives" optgroup and the full
// canonical catalog), an Ignore toggle, a confidence chip, and a "Why" reasoning line. The create
// persists the HUMAN-EDITED targets, not the raw suggestion. These tests drive the wizard to the
// mapping step and assert: (fixture) the editable controls render + gating blocks an unmapped
// non-ignored field; (real, fetch-spy) editing a target then activating POSTs the EDITED dest_key.

const CSV = 'sku,qty,price\nTS-RED-M,2,12.99\n'
function csvFile(text: string = CSV): File {
  return new File([text], 'sales.csv', { type: 'text/csv' })
}

function renderWizard(): { container: HTMLElement } {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const tree: ReactNode = (
    <QueryClientProvider client={qc}>
      <CsvWizard onBack={() => {}} />
    </QueryClientProvider>
  )
  return render(tree)
}

// Drive Source&method -> Upload -> Locale -> Data type -> AI mapping (step 4).
async function driveToMapping(
  container: HTMLElement,
  file: File = csvFile(),
  typeLabel = 'Sales',
): Promise<void> {
  const user = userEvent.setup()
  const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement
  await user.upload(fileInput, file)
  // Continue on step 1 is the first control by that name; label-agnostic to survive the step-4
  // issue-count relabel ("Continue — N issues").
  await user.click(await screen.findByRole('button', { name: /^Continue/ })) // step 1 -> 2
  await user.click(await screen.findByRole('button', { name: /^Continue/ })) // step 2 -> 3 (locale)
  await user.click(await screen.findByText(typeLabel)) // pick the template type
  await user.click(await screen.findByRole('button', { name: /^Continue/ })) // step 3 -> 4
  // The editable mapping step has rendered once the per-field target selects exist (every test CSV
  // carries a `sku` column).
  await screen.findByLabelText('Canonical target for sku')
}

afterEach(() => {
  vi.unstubAllEnvs()
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('CsvWizard AI mapping — editable (fixture mode)', () => {
  it('renders per-field target selects seeded from the suggestion, chips, and Ignore controls', async () => {
    const { container } = renderWizard()
    await driveToMapping(container)
    // The suggested target pre-selects the <select> (mechanical fallback: sku -> sku_id, etc.).
    const skuSelect = (await screen.findByLabelText('Canonical target for sku')) as HTMLSelectElement
    expect(skuSelect.value).toBe('sku_id')
    expect((screen.getByLabelText('Canonical target for qty') as HTMLSelectElement).value).toBe('quantity')
    // Ignore toggle per row + honest producer label (fixture -> mechanical fallback).
    expect(screen.getByLabelText('Ignore sku')).toBeInTheDocument()
    expect(screen.getByText('Suggestions: basic match')).toBeInTheDocument()
    // Confidence chip (0.95 -> High for the synonym hits).
    expect(screen.getAllByText(/High$/).length).toBeGreaterThan(0)
  })

  // A fully-valid snapshot mapping (only sku_id is mandatory) passes every client check and
  // enables Continue; unmapping the required field disables it again.
  it('a valid mapping passes client-side checks and enables Continue; unmapping breaks it', async () => {
    const { container } = renderWizard()
    await driveToMapping(container, csvFile('sku\nTS-RED-M\n'), 'Catalogue snapshot')
    const user = userEvent.setup()
    // Force the one mandatory snapshot field mapped, deterministically.
    await user.selectOptions(screen.getByLabelText('Canonical target for sku'), 'sku_id')
    expect(screen.getByText('All checks passing')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Continue/ })).toBeEnabled()
    // Unmap it: required-coverage + columns-resolved both fail -> Continue disabled + relabeled.
    await user.selectOptions(screen.getByLabelText('Canonical target for sku'), '')
    expect(screen.getByRole('button', { name: /^Continue/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /2 issues/ })).toBeInTheDocument()
  })

  // Duplicate target: two source columns pointing at one field are detected, both rows are flagged
  // inline with a danger message, and Continue is blocked.
  it('detects a duplicate target, flags the rows inline, and blocks Continue', async () => {
    const { container } = renderWizard()
    await driveToMapping(container) // Sales
    const user = userEvent.setup()
    // sku already maps to sku_id; point qty at sku_id too -> collision on sku_id.
    await user.selectOptions(screen.getByLabelText('Canonical target for qty'), 'sku_id')
    // Panel: a DUPLICATE-class issue, naming the actual target (its catalog label) + the action.
    expect(screen.getByText('Duplicate')).toBeInTheDocument() // class tag
    expect(screen.getByText(/Two columns map to SKU\. Each field can receive only one column/)).toBeInTheDocument()
    // Inline: both colliding rows carry the duplicate danger message.
    const dupMsgs = screen.getAllByText(/mapped by more than one column/i)
    expect(dupMsgs.length).toBe(2)
    // Continue blocked.
    expect(screen.getByRole('button', { name: /^Continue/ })).toBeDisabled()
  })

  // Missing required field: the catalog's `mandatory` flag drives detection (no hardcoded list).
  // Sales requires 8 fields; the 3-column fixture cannot cover them, so the check fails and names
  // a missing field.
  it('detects a missing required field from the catalog mandatory flag and blocks Continue', async () => {
    const { container } = renderWizard()
    await driveToMapping(container) // Sales, only sku/qty/price mappable
    // Panel: a REQUIRED-class issue leading with the count + the missing field labels, then action.
    expect(screen.getByText('Required')).toBeInTheDocument() // class tag
    expect(screen.getByText(/required fields still need a column:.*Currency/)).toBeInTheDocument()
    expect(screen.getByText(/can't be used with this template/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Continue/ })).toBeDisabled()
  })

  // The panel count is honest and re-renders as the mapping is edited.
  it('updates the checklist count as the mapping is edited', async () => {
    const { container } = renderWizard()
    await driveToMapping(container, csvFile('sku\nTS-RED-M\n'), 'Catalogue snapshot')
    const user = userEvent.setup()
    await user.selectOptions(screen.getByLabelText('Canonical target for sku'), 'sku_id')
    expect(screen.getByText('All checks passing')).toBeInTheDocument()
    // Unmap -> only unique-targets still passes.
    await user.selectOptions(screen.getByLabelText('Canonical target for sku'), '')
    expect(screen.getByText('2 issues to fix before continuing')).toBeInTheDocument()
  })

  // Item 2a — a 0%-confidence fallback pick (argmax-defaulted, no real match) seeds as Unmapped,
  // NOT the defaulted catalog field. Fixture mode always uses the mechanical fallback matcher.
  it('seeds a 0%-confidence fallback field as Unmapped, not the defaulted target', async () => {
    // 'sku' matches (synonym -> sku_id @ 0.95); 'mystery_col' matches nothing -> argmax default at 0%.
    const { container } = renderWizard()
    await driveToMapping(container, csvFile('sku,mystery_col\nA,B\n'))
    // matched column keeps its real suggestion.
    expect((screen.getByLabelText('Canonical target for sku') as HTMLSelectElement).value).toBe('sku_id')
    // the 0%-confidence column is Unmapped ('') — NOT pre-selected to the defaulted first field.
    const mystery = screen.getByLabelText('Canonical target for mystery_col') as HTMLSelectElement
    expect(mystery.value).toBe('')
    expect(mystery.value).not.toBe('event_date')
  })

  // Item 2b — fallback shows an honest "set manually" banner and NO retry button.
  it('shows the fallback banner (no retry button) when suggestions are the mechanical fallback', async () => {
    const { container } = renderWizard()
    await driveToMapping(container)
    expect(screen.getByText(/AI mapping is unavailable right now/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /retry/i })).toBeNull()
    // honest producer label reflects the fallback.
    expect(screen.getByText('Suggestions: basic match')).toBeInTheDocument()
  })
})

describe('CsvWizard parsing profile — locale radio group (fixture mode)', () => {
  // Drive Source&method -> Parsing profile (step 2), where the locale control lives.
  async function driveToLocale(container: HTMLElement): Promise<HTMLElement> {
    const user = userEvent.setup()
    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement
    await user.upload(fileInput, csvFile())
    await user.click(await screen.findByRole('button', { name: /^Continue/ })) // step 1 -> 2
    // The fieldset+legend expose the group by its accessible name.
    return screen.findByRole('group', { name: 'Number & date locale' })
  }
  const hintText = (container: HTMLElement): string => container.querySelector('.hint')?.textContent ?? ''

  it('renders the locale control as a radio group, US selected by default', async () => {
    const { container } = renderWizard()
    await driveToLocale(container)
    // Three real radios (not a <select>); no locale combobox remains.
    expect(screen.getAllByRole('radio')).toHaveLength(3)
    expect(screen.queryByRole('combobox', { name: /locale/i })).toBeNull()
    // Default preserved: US.
    expect((screen.getByRole('radio', { name: 'US (1,234.56)' }) as HTMLInputElement).checked).toBe(true)
    expect((screen.getByRole('radio', { name: 'EU (1.234,56)' }) as HTMLInputElement).checked).toBe(false)
    expect((screen.getByRole('radio', { name: "Swiss (1'234.56)" }) as HTMLInputElement).checked).toBe(false)
    // The value the wizard consumes (the `locale` state) drives the hint: US = decimal '.', thousands ','.
    expect(hintText(container)).toContain('thousands “,”')
  })

  it('selecting a radio flows to the same locale state the <select> set', async () => {
    const { container } = renderWizard()
    await driveToLocale(container)
    const user = userEvent.setup()
    await user.click(screen.getByRole('radio', { name: 'EU (1.234,56)' }))
    // Selection moved to EU; US cleared (single group).
    expect((screen.getByRole('radio', { name: 'EU (1.234,56)' }) as HTMLInputElement).checked).toBe(true)
    expect((screen.getByRole('radio', { name: 'US (1,234.56)' }) as HTMLInputElement).checked).toBe(false)
    // Consumed value changed: hint now reflects the EU preset (decimal ',', thousands '.').
    expect(hintText(container)).toContain('thousands “.”')
  })
})

// ---- Real mode (fetch spy): the edited mapping is what gets persisted ----

type FetchCall = { url: string; method: string; body: unknown }

function catalogField(key: string, section: string, datatype: string | null): Record<string, unknown> {
  return {
    key,
    display_name: key,
    section,
    mandatory: false,
    constraints: null,
    datatype,
    description: '',
    allowed_values: null,
    max_length: null,
    sink: section === 'system' ? null : 'store_sku_sale_event',
  }
}

// A configurable real-mode fetch spy for the dry-run tests: an all-optional catalog (client-side
// checks pass, so the DRY-RUN outcome is what's under test), a two-column suggestion, and tunable
// validate / create outcomes. `'ok'` = success; `'throw'` = transport failure; an envelope object =
// a non-2xx with that {code,message}.
type SpyEnvelope = { status: number; code: string; message: string }
function errorBody(code: string, message: string): string {
  return JSON.stringify({ error: { code, message, trace_id: 't', details: {} } })
}
function dryRunSpy(cfg: { validate?: SpyEnvelope | 'throw' | 'ok'; create?: SpyEnvelope | 'ok' } = {}) {
  return vi.fn(async (input: unknown, init?: RequestInit) => {
    const url = String(input)
    const method = (init?.method ?? 'GET').toUpperCase()
    if (url.includes('/template-types')) {
      return new Response(JSON.stringify([{ key: 'sales', display_name: 'Sales', description: 'x' }]), { status: 200 })
    }
    if (url.includes('/template-mapping-fields')) {
      return new Response(
        JSON.stringify([catalogField('sku_id', 'sale_event', 'text'), catalogField('quantity', 'sale_event', 'number')]),
        { status: 200 },
      )
    }
    if (url.includes('/mapping-suggestions')) {
      return new Response(
        JSON.stringify({
          source: 'llm',
          model: 'g',
          suggestions: [
            { source_column: 'sku', suggested_target: 'sku_id', confidence: 0.9 },
            { source_column: 'qty', suggested_target: 'quantity', confidence: 0.85 },
          ],
        }),
        { status: 200 },
      )
    }
    if (url.includes('/sources')) {
      return new Response(JSON.stringify({ source_id: 's', display_name: 's', channel: 'csv_upload' }), { status: 201 })
    }
    if (url.includes('/mapping-templates/validate')) {
      const v = cfg.validate ?? 'ok'
      if (v === 'throw') throw new Error('network down')
      if (v === 'ok') return new Response(JSON.stringify({ valid: true }), { status: 200 })
      return new Response(errorBody(v.code, v.message), { status: v.status })
    }
    if (url.includes('/mapping-templates') && method === 'POST') {
      const c = cfg.create ?? 'ok'
      if (c === 'ok') {
        return new Response(
          JSON.stringify({ template_id: 't', template_name: 'sales', template_type: 'sales', active_version: 1, draft_version: null }),
          { status: 201 },
        )
      }
      return new Response(errorBody(c.code, c.message), { status: c.status })
    }
    return new Response('{}', { status: 200 })
  })
}

describe('CsvWizard AI mapping — real mode persists the EDITED target (fetch spy)', () => {
  it('POSTs /mapping-templates with the human-edited dest_key, not the suggestion', async () => {
    vi.stubEnv('VITE_DIS_UI_SERVER_MODE', 'real')
    writeToken('stub.session.token')
    const calls: FetchCall[] = []
    const fetchSpy = vi.fn(async (input: unknown, init?: RequestInit) => {
      const url = String(input)
      const method = (init?.method ?? 'GET').toUpperCase()
      const body = init?.body != null ? JSON.parse(String(init.body)) : null
      calls.push({ url, method, body })
      if (url.includes('/template-types')) {
        return new Response(JSON.stringify([{ key: 'sales', display_name: 'Sales', description: 'x' }]), { status: 200 })
      }
      if (url.includes('/template-mapping-fields')) {
        return new Response(
          JSON.stringify([
            catalogField('sku_id', 'sale_event', 'text'),
            catalogField('sku_variant', 'sale_event', 'text'),
            catalogField('quantity', 'sale_event', 'number'),
            catalogField('unit_sale_price', 'sale_event', 'number'),
            catalogField('__ignore__', 'system', null),
          ]),
          { status: 200 },
        )
      }
      if (url.includes('/mapping-suggestions')) {
        return new Response(
          JSON.stringify({
            source: 'llm',
            model: 'gemini-2.5-flash',
            suggestions: [
              { source_column: 'sku', suggested_target: 'sku_id', confidence: 0.9, alternatives: ['sku_variant'] },
              { source_column: 'qty', suggested_target: 'quantity', confidence: 0.85 },
              { source_column: 'price', suggested_target: 'unit_sale_price', confidence: 0.7 },
            ],
          }),
          { status: 200 },
        )
      }
      if (url.includes('/sources')) {
        return new Response(JSON.stringify({ source_id: 's', display_name: 's', channel: 'csv_upload' }), { status: 201 })
      }
      // The dry-run validate (fired at Continue) — MUST be matched before the create branch.
      if (url.includes('/mapping-templates/validate')) {
        return new Response(JSON.stringify({ valid: true }), { status: 200 })
      }
      if (url.includes('/mapping-templates')) {
        return new Response(
          JSON.stringify({
            template_id: 'tmpl_x',
            template_name: 'sales',
            template_type: 'sales',
            active_version: 1,
            draft_version: null,
          }),
          { status: 201 },
        )
      }
      return new Response('{}', { status: 200 })
    })
    vi.stubGlobal('fetch', fetchSpy)

    const { container } = renderWizard()
    await driveToMapping(container)
    const user = userEvent.setup()

    // The LLM suggested sku -> sku_id; the operator EDITS it to sku_variant, and IGNORES price.
    await user.selectOptions(await screen.findByLabelText('Canonical target for sku'), 'sku_variant')
    await user.click(screen.getByLabelText('Ignore price'))

    // Continue fires the dry-run (200 valid) then advances. Wait for the step-4-only mapping panel
    // to disappear (the dry-run is async — the step-4 Continue stays on-screen while it is pending;
    // the StepRail echoes every step's subtitle, so text markers are ambiguous).
    await user.click(await screen.findByRole('button', { name: /^Continue/ })) // step 4 -> 5
    await waitFor(() => expect(screen.queryByLabelText('Mapping checks')).toBeNull()) // now off step 4
    await user.click(screen.getByRole('button', { name: /^Continue/ })) // step 5 -> 6
    await user.click(await screen.findByRole('button', { name: 'Activate template' }))

    await screen.findByText(/Template created/)

    const validate = calls.find((c) => c.method === 'POST' && c.url.includes('/mapping-templates/validate'))
    const create = calls.find(
      (c) => c.method === 'POST' && c.url.includes('/mapping-templates') && !c.url.includes('/validate'),
    )
    expect(validate).toBeDefined()
    expect(create).toBeDefined()
    // The dry-run submitted the IDENTICAL body the create submitted (one shared builder).
    expect(validate!.body).toEqual(create!.body)
    const columns = (create!.body as { columns: { src_key: string; dest_key: string }[] }).columns
    // sku carries the EDITED target, NOT the suggestion (sku_id).
    const sku = columns.find((c) => c.src_key === 'sku')
    expect(sku?.dest_key).toBe('sku_variant')
    expect(sku?.dest_key).not.toBe('sku_id')
    // qty keeps the (unedited) suggestion; price is the ignored sentinel.
    expect(columns.find((c) => c.src_key === 'qty')?.dest_key).toBe('quantity')
    expect(columns.find((c) => c.src_key === 'price')?.dest_key).toBe('__ignore__')
  })

  // FIX 1 (double-fire): /mapping-suggestions (the Vertex-hitting LLM call) must fire EXACTLY ONCE
  // per mapping step and must NOT refire on a window focus (the root cause of the deploy 429s).
  it('fires /mapping-suggestions exactly once and does not refire on window focus', async () => {
    vi.stubEnv('VITE_DIS_UI_SERVER_MODE', 'real')
    writeToken('stub.session.token')
    let suggestionCalls = 0
    const fetchSpy = vi.fn(async (input: unknown) => {
      const url = String(input)
      if (url.includes('/template-types')) {
        return new Response(JSON.stringify([{ key: 'sales', display_name: 'Sales', description: 'x' }]), { status: 200 })
      }
      if (url.includes('/template-mapping-fields')) {
        return new Response(
          JSON.stringify([catalogField('sku_id', 'sale_event', 'text'), catalogField('quantity', 'sale_event', 'number')]),
          { status: 200 },
        )
      }
      if (url.includes('/mapping-suggestions')) {
        suggestionCalls += 1
        return new Response(
          JSON.stringify({
            source: 'llm',
            model: 'gemini-2.5-flash',
            suggestions: [{ source_column: 'sku', suggested_target: 'sku_id', confidence: 0.9 }],
          }),
          { status: 200 },
        )
      }
      return new Response('{}', { status: 200 })
    })
    vi.stubGlobal('fetch', fetchSpy)

    const { container } = renderWizard()
    await driveToMapping(container)
    expect(suggestionCalls).toBe(1)

    // A tab blur→focus during/after the call must NOT refire it (staleTime Infinity +
    // refetchOnWindowFocus:false on the analysis query).
    window.dispatchEvent(new Event('focus'))
    await new Promise((r) => setTimeout(r, 0))
    expect(suggestionCalls).toBe(1)
  })

  // A dry-run 400 (a backend-only companion-group failure) surfaces AT the Continue step: the
  // panel shows the backend message and Continue is blocked, without advancing. Client-side checks
  // pass (all-optional catalog), so this proves combined gating — the backend issue alone blocks.
  it('surfaces a companion-group 400 at Continue and blocks advancing', async () => {
    vi.stubEnv('VITE_DIS_UI_SERVER_MODE', 'real')
    writeToken('stub.session.token')
    vi.stubGlobal('fetch', dryRunSpy({ validate: { status: 400, code: 'mapping_config', message: 'promo_identifier requires promo_price' } }))

    const { container } = renderWizard()
    await driveToMapping(container, csvFile('sku,qty\nA,2\n'))
    const user = userEvent.setup()
    // BEFORE Continue: client-side checks pass and the Dependent (server-only) class is NOT shown —
    // no pre-check placeholder for a check that hasn't run.
    await screen.findByText('All checks passing')
    expect(screen.queryByText('Dependent')).toBeNull()
    await user.click(await screen.findByRole('button', { name: /^Continue/ })) // fire dry-run
    // AFTER the 400: a Dependent-class issue with the backend's prose; Continue blocked; not advanced.
    await screen.findByText('promo_identifier requires promo_price')
    expect(screen.getByText('Dependent')).toBeInTheDocument() // class tag, server-surfaced only
    expect(screen.getByRole('button', { name: /1 issue/ })).toBeDisabled()
    expect(screen.getByLabelText('Mapping checks')).toBeInTheDocument()
  })

  // A dry-run 403 is the WRONG PERSONA for a tenant-scoped mapping (handled like the create 403),
  // NOT a validation issue: a soft note, no fabricated "Fix" line, and Continue proceeds.
  it('treats a dry-run 403 as a persona note, not a validation issue, and proceeds', async () => {
    vi.stubEnv('VITE_DIS_UI_SERVER_MODE', 'real')
    writeToken('stub.session.token')
    vi.stubGlobal('fetch', dryRunSpy({ validate: { status: 403, code: 'tenant_scope', message: 'wrong persona' } }))

    const { container } = renderWizard()
    await driveToMapping(container, csvFile('sku,qty\nA,2\n'))
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: /^Continue/ })) // fire dry-run -> 403
    await screen.findByText(/your role can't validate it here/i) // soft persona note
    // NOT rendered as a validation issue, and Continue is not blocked.
    expect(screen.queryByText('wrong persona')).toBeNull()
    expect(screen.getByRole('button', { name: /^Continue/ })).toBeEnabled()
    // A second press proceeds (Activate is where the persona 403 would surface, as before).
    await user.click(screen.getByRole('button', { name: /^Continue/ }))
    await waitFor(() => expect(screen.queryByLabelText('Mapping checks')).toBeNull()) // advanced off step 4
  })

  // Backstop honesty: a TRANSPORT failure of the dry-run (not a 400) does NOT claim valid/invalid
  // and does NOT falsely block — a soft note, Continue proceeds, and the Activate 400 remains the
  // backstop that surfaces the real companion-group error.
  it('on a dry-run transport failure, notes softly, proceeds, and Activate is the backstop', async () => {
    vi.stubEnv('VITE_DIS_UI_SERVER_MODE', 'real')
    writeToken('stub.session.token')
    vi.stubGlobal(
      'fetch',
      dryRunSpy({
        validate: 'throw',
        create: { status: 400, code: 'mapping_config', message: 'the expiry triple is all-or-none' },
      }),
    )

    const { container } = renderWizard()
    await driveToMapping(container, csvFile('sku,qty\nA,2\n'))
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: /^Continue/ })) // dry-run transport-fails
    await screen.findByText(/Couldn't reach validation/i) // soft note, no fabricated issue
    // Not falsely blocked: Continue is still enabled, and no backend "Fix" issue was invented.
    expect(screen.getByRole('button', { name: /^Continue/ })).toBeEnabled()
    expect(screen.queryByText('the expiry triple is all-or-none')).toBeNull()
    // Proceed through to Activate — the create 400 is the backstop that surfaces the real error.
    await user.click(screen.getByRole('button', { name: /^Continue/ })) // step 4 -> 5 (softFailed proceeds)
    await waitFor(() => expect(screen.queryByLabelText('Mapping checks')).toBeNull())
    await user.click(screen.getByRole('button', { name: /^Continue/ })) // step 5 -> 6
    await user.click(await screen.findByRole('button', { name: 'Activate template' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('the expiry triple is all-or-none')
  })
})
