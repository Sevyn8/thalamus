import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { writeToken } from '../../auth/storage'
import type { CreateCsvTemplateInput } from './connectors-api'
import type { CatalogField } from './mapping-fields'
import type { MappingRow } from './mapping-validation'
import {
  checkColumnsResolved,
  checkRequiredCoverage,
  checkUniqueTargets,
  offendingRowSet,
  runBackendDryRun,
  runClientSideChecks,
} from './mapping-validation'

function row(sourceField: string, target: string, ignored = false): MappingRow {
  return { sourceField, target, ignored }
}

function field(key: string, mandatory: boolean): CatalogField {
  return {
    key,
    display_name: key,
    section: 'sale_event',
    mandatory,
    constraints: null,
    datatype: 'text',
    description: '',
    allowed_values: null,
    max_length: null,
    sink: 'store_sku_sale_event',
  }
}

describe('mapping-validation client-side checks', () => {
  it('checkUniqueTargets: Duplicate class, names the target + count, gives the change/ignore action', () => {
    const issue = checkUniqueTargets([row('sku', 'sku_id'), row('code', 'sku_id'), row('qty', 'quantity')])
    expect(issue).not.toBeNull()
    expect(issue?.id).toBe('unique-targets')
    expect(issue?.classLabel).toBe('Duplicate')
    expect(issue?.severity).toBe('error')
    expect(new Set(issue?.offendingRows)).toEqual(new Set(['sku', 'code']))
    expect(issue?.message).toBe('Two columns map to sku_id. Each field can receive only one column. Change or ignore one.')
  })

  it('checkUniqueTargets: names the catalog LABEL of the duplicated target when the catalog is given', () => {
    const catalog: CatalogField[] = [{ ...field('current_retail_price', false), display_name: 'Current retail price' }]
    const issue = checkUniqueTargets([row('a', 'current_retail_price'), row('b', 'current_retail_price')], catalog)
    expect(issue?.message).toContain('Current retail price') // label, not the raw key
  })

  it('checkUniqueTargets ignores ignored/unmapped rows (no false collision)', () => {
    // Two rows would both be sku_id, but one is ignored and one is Unmapped -> no active collision.
    expect(checkUniqueTargets([row('sku', 'sku_id'), row('code', 'sku_id', true), row('x', '')])).toBeNull()
  })

  it('checkRequiredCoverage names unmapped mandatory fields and carries no offendingRows', () => {
    const catalog = [field('sku_id', true), field('currency', true), field('note', false)]
    const issue = checkRequiredCoverage([row('sku', 'sku_id')], catalog)
    expect(issue?.id).toBe('required-coverage')
    expect(issue?.classLabel).toBe('Required')
    // Leads with the count + the specific field label, then the corrected action (no "ignore the file").
    expect(issue?.message).toContain('1 required field still needs a column: currency')
    expect(issue?.message).toContain("can't be used with this template")
    expect(issue?.message).not.toContain('ignore the file')
    expect(issue?.offendingRows).toBeUndefined() // a missing field has no row to anchor to
  })

  it('checkRequiredCoverage passes when every mandatory field is mapped', () => {
    const catalog = [field('sku_id', true), field('note', false)]
    expect(checkRequiredCoverage([row('sku', 'sku_id')], catalog)).toBeNull()
  })

  it('checkColumnsResolved flags unmapped, non-ignored rows only', () => {
    const issue = checkColumnsResolved([row('sku', 'sku_id'), row('x', ''), row('y', '', true)])
    expect(issue?.id).toBe('columns-resolved')
    expect(issue?.classLabel).toBe('Unmapped')
    expect(issue?.offendingRows).toEqual(['x'])
  })

  it('runClientSideChecks returns [] for a fully valid mapping', () => {
    const catalog = [field('sku_id', true), field('note', false)]
    expect(runClientSideChecks([row('sku', 'sku_id'), row('n', 'note')], catalog)).toEqual([])
  })

  it('offendingRowSet unions offendingRows across issues', () => {
    const issues = runClientSideChecks(
      [row('sku', 'sku_id'), row('code', 'sku_id'), row('x', '')],
      [field('sku_id', true)],
    )
    // unique-targets flags sku+code; columns-resolved flags x.
    expect(offendingRowSet(issues)).toEqual(new Set(['sku', 'code', 'x']))
  })
})

// runBackendDryRun exercised against the REAL client path (real mode + stubbed fetch): this covers
// validateCsvTemplate -> postJson -> the shared envelope parser (DisUiServerHttpError) -> the
// outcome mapping, end to end. An envelope mirrors the backend shape {error:{code,message,...}}.
function envelope(code: string, message: string): string {
  return JSON.stringify({ error: { code, message, trace_id: 't', details: {} } })
}

describe('mapping-validation backend dry-run', () => {
  const INPUT: CreateCsvTemplateInput = {
    sourceId: 'manual_csv_upload',
    templateName: 'catalogue',
    templateType: 'snapshot',
    columns: [{ src_key: 'a', dest_key: 'sku_id' }],
  }

  beforeEach(() => {
    vi.stubEnv('VITE_DIS_UI_SERVER_MODE', 'real')
    writeToken('stub.session.token')
  })
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.restoreAllMocks()
    localStorage.clear()
  })

  it('200 {valid:true} -> ok with no issues', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ valid: true }), { status: 200 })))
    expect(await runBackendDryRun(INPUT)).toEqual({ status: 'ok', issues: [] })
  })

  it('400 envelope -> ok with one panel-only issue carrying the backend message', async () => {
    const msg = 'the expiry triple is all-or-none'
    vi.stubGlobal('fetch', vi.fn(async () => new Response(envelope('mapping_config', msg), { status: 400 })))
    const outcome = await runBackendDryRun(INPUT)
    expect(outcome.status).toBe('ok')
    if (outcome.status !== 'ok') throw new Error('expected ok')
    expect(outcome.issues).toHaveLength(1)
    expect(outcome.issues[0].classLabel).toBe('Dependent') // companion-group = the Dependent class
    expect(outcome.issues[0].severity).toBe('error')
    expect(outcome.issues[0].message).toBe(msg) // the SAME message the Activate failbox shows
    expect(outcome.issues[0].offendingRows).toBeUndefined() // panel-only: envelope names no columns
  })

  it('403 -> forbidden (wrong persona), never a validation issue', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(envelope('tenant_scope', 'nope'), { status: 403 })))
    expect(await runBackendDryRun(INPUT)).toEqual({ status: 'forbidden' })
  })

  it('transport failure -> unreachable, no fabricated issues', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('network down') }))
    expect(await runBackendDryRun(INPUT)).toEqual({ status: 'unreachable' })
  })

  it('5xx -> unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(envelope('internal', 'boom'), { status: 500 })))
    expect(await runBackendDryRun(INPUT)).toEqual({ status: 'unreachable' })
  })
})
