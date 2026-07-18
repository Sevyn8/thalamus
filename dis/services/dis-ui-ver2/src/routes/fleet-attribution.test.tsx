import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { AuthSnapshot } from '../auth/AuthSnapshot'
import { AuthContext } from '../auth/context'
import type { AuthContextValue } from '../auth/context'
import { writeToken } from '../auth/storage'
import type { RunRow } from '../lib/dis-ui-server/runs'
import { Audit } from './Audit'
import { ConnectorHealth } from './ConnectorHealth'
import { IngestionRuns } from './IngestionRuns'
import { Sources } from './Sources'

// Chunk 3: fleet attribution (Tenant column + tenant filter) on the four PLATFORM surfaces. Fixture
// mode; the fixtures span two tenants (…a1 / …b2), and audit also carries a null-tenant system row.
const A_SHORT = '…0000000000a1'
const B_SHORT = '…0000000000b2'

const TENANT: AuthSnapshot = {
  userId: 'u',
  tenantId: 't_acme9k2l1mn4',
  storeId: 's',
  userType: 'TENANT',
  roles: ['dis:read'],
}
const PLATFORM: AuthSnapshot = {
  userId: 'anjali',
  tenantId: null,
  storeId: null,
  userType: 'PLATFORM',
  roles: ['dis:ops', 'dis:read'],
}

function renderAs(snapshot: AuthSnapshot, ui: ReactNode) {
  const authValue: AuthContextValue = {
    status: 'authenticated',
    snapshot,
    login: () => Promise.resolve(),
    logout: () => {},
  }
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <AuthContext.Provider value={authValue}>
        <MemoryRouter>{ui}</MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Ingestion Runs — fleet attribution', () => {
  it('PLATFORM: Tenant column (shortened UUID, full tooltip) + auto-populated tenant filter that narrows; page-local note', async () => {
    renderAs(PLATFORM, <IngestionRuns />)
    expect(await screen.findByRole('columnheader', { name: 'Tenant' })).toBeInTheDocument()
    // Keyset caveat surfaced.
    expect(screen.getByText('Tenant filters the loaded page.')).toBeInTheDocument()
    const table = screen.getByRole('table')
    expect(within(table).getAllByText(A_SHORT).length).toBeGreaterThan(0) // shortened UUID, no fabricated name
    // Filter auto-populated from present tenant_ids; selecting one narrows the loaded page.
    const tenantSel = screen.getByLabelText('Tenant') as HTMLSelectElement
    expect([...tenantSel.options].map((o) => o.textContent)).toEqual(expect.arrayContaining([A_SHORT, B_SHORT]))
    await userEvent.setup().selectOptions(tenantSel, screen.getByRole('option', { name: B_SHORT }))
    expect(within(screen.getByRole('table')).queryAllByText(A_SHORT).length).toBe(0)
  })

  it('PLATFORM: row-click still opens the shared drawer', async () => {
    renderAs(PLATFORM, <IngestionRuns />)
    await screen.findByRole('table')
    await userEvent.setup().click(screen.getAllByRole('row').slice(1)[0])
    expect(await screen.findByRole('dialog', { name: 'Ingestion run detail' })).toBeInTheDocument()
  })

  it('PLATFORM: existing status filter still works alongside the tenant filter', async () => {
    renderAs(PLATFORM, <IngestionRuns />)
    await screen.findByRole('table')
    // The domain filter (status) is intact.
    await userEvent.setup().selectOptions(screen.getByLabelText('Status'), 'failed')
    const table = screen.getByRole('table')
    // Only failed runs remain (fixture 103 is the failed run, tenant B).
    expect(within(table).getAllByText(B_SHORT).length).toBeGreaterThan(0)
  })

  it('TENANT: no Tenant column and no tenant filter', async () => {
    renderAs(TENANT, <IngestionRuns />)
    await screen.findByRole('table')
    expect(screen.queryByRole('columnheader', { name: 'Tenant' })).toBeNull()
    expect(screen.queryByLabelText('Tenant')).toBeNull()
    expect(screen.queryByText('Tenant filters the loaded page.')).toBeNull()
  })
})

describe('Connector Health — fleet attribution', () => {
  it('PLATFORM: cards carry a Tenant line + tenant filter narrows; combines with the status filter', async () => {
    renderAs(PLATFORM, <ConnectorHealth />)
    // Cards render a Tenant kv line (shortened UUID).
    expect(await screen.findAllByText(A_SHORT)).not.toHaveLength(0)
    const tenantSel = screen.getByLabelText('Tenant') as HTMLSelectElement
    expect([...tenantSel.options].map((o) => o.textContent)).toEqual(expect.arrayContaining([A_SHORT, B_SHORT]))
    // Tenant + Status combine (AND): tenant B, then a status only B has.
    await userEvent.setup().selectOptions(tenantSel, screen.getByRole('option', { name: B_SHORT }))
    expect(screen.queryAllByText(A_SHORT).filter((el) => el.className.includes('mono')).length).toBe(0)
  })

  it('TENANT: no tenant filter and no Tenant line on cards', async () => {
    renderAs(TENANT, <ConnectorHealth />)
    await screen.findAllByText(/Manual CSV|healthy|stale/i)
    expect(screen.queryByLabelText('Tenant')).toBeNull()
    expect(screen.queryByText(A_SHORT)).toBeNull()
  })
})

describe('Sources — fleet attribution', () => {
  it('PLATFORM: Tenant column + tenant filter that narrows', async () => {
    renderAs(PLATFORM, <Sources />)
    expect(await screen.findByRole('columnheader', { name: 'Tenant' })).toBeInTheDocument()
    const table = screen.getByRole('table')
    expect(within(table).getAllByText(A_SHORT).length).toBeGreaterThan(0)
    await userEvent.setup().selectOptions(screen.getByLabelText('Tenant'), screen.getByRole('option', { name: B_SHORT }))
    expect(within(screen.getByRole('table')).queryAllByText(A_SHORT).length).toBe(0)
    expect(within(screen.getByRole('table')).getAllByText(B_SHORT).length).toBeGreaterThan(0)
  })

  it('TENANT: no Tenant column and no tenant filter', async () => {
    renderAs(TENANT, <Sources />)
    await screen.findByRole('table')
    expect(screen.queryByRole('columnheader', { name: 'Tenant' })).toBeNull()
    expect(screen.queryByLabelText('Tenant')).toBeNull()
  })
})

describe('Audit — fleet attribution', () => {
  it('PLATFORM: Tenant column; null-tenant row → "System / platform"; tenant filter incl. System narrows; outcome filter intact', async () => {
    renderAs(PLATFORM, <Audit />)
    expect(await screen.findByRole('columnheader', { name: 'Tenant' })).toBeInTheDocument()
    const table = screen.getByRole('table')
    // The null-tenant (system) fixture row is attributed as "System / platform", NOT a fabricated tenant.
    expect(within(table).getByText('System / platform')).toBeInTheDocument()
    expect(within(table).getAllByText(A_SHORT).length).toBeGreaterThan(0)
    // Tenant filter includes the System option and narrows to it.
    const tenantSel = screen.getByLabelText('Tenant') as HTMLSelectElement
    expect([...tenantSel.options].map((o) => o.textContent)).toEqual(
      expect.arrayContaining([A_SHORT, B_SHORT, 'System / platform']),
    )
    await userEvent.setup().selectOptions(tenantSel, screen.getByRole('option', { name: 'System / platform' }))
    const rows = within(screen.getByRole('table')).getAllByRole('row').slice(1)
    expect(rows.every((r) => within(r).queryByText('System / platform') !== null)).toBe(true)
    // The domain (outcome) filter control is still present.
    expect(screen.getByLabelText('Outcome')).toBeInTheDocument()
  })

  it('TENANT: no Tenant column and no tenant filter', async () => {
    renderAs(TENANT, <Audit />)
    await screen.findByRole('table')
    expect(screen.queryByRole('columnheader', { name: 'Tenant' })).toBeNull()
    expect(screen.queryByLabelText('Tenant')).toBeNull()
  })
})

// Chunk 9-FE: when the backend serves tenant_name, the fleet surfaces DISPLAY the name (UUID in the
// tooltip); a null name falls back to the shortened UUID. Proven on Ingestion Runs (real mode) — the
// four fleet surfaces share the one tenantName helper, so this is representative.
function runRow(over: Partial<RunRow> & Pick<RunRow, 'id' | 'tenant_id'>): RunRow {
  return {
    trace_id: '0190ac0e-1a01-7001-8a01-0000000000e1',
    tenant_name: null,
    store_id: null,
    store_name: null,
    source_id: 'src_a',
    source_name: null,
    template_id: null,
    template_name: null,
    method: 'csv_upload',
    status: 'succeeded',
    mapping_version: 1,
    seen_before: false,
    source_payload_id: null,
    file_name: null,
    input_row_count: 100,
    accepted: 100,
    quarantined: 0,
    received_at: '2026-07-16T10:00:00Z',
    published_at: null,
    completed_at: null,
    ...over,
  }
}

describe('Chunk 9-FE: fleet surfaces display tenant_name (Ingestion Runs, real mode)', () => {
  const A = '0190ac10-1a01-7001-8a01-0000000000a1'
  const B = '0190ac10-1a01-7001-8a01-0000000000b2'

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.restoreAllMocks()
    localStorage.clear()
  })

  function stubRuns(): void {
    vi.stubEnv('VITE_DIS_UI_SERVER_MODE', 'real')
    writeToken('stub.session.token')
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const url = String(input)
        if (url.includes('/runs')) {
          return new Response(
            JSON.stringify({
              items: [
                runRow({ id: 'r1', tenant_id: A, tenant_name: 'Buc-ees' }),
                runRow({ id: 'r2', tenant_id: B, tenant_name: null }), // null name → UUID fallback
              ],
              next_cursor: null,
            }),
            { status: 200 },
          )
        }
        return new Response(JSON.stringify({ items: [] }), { status: 200 })
      }),
    )
  }

  it('Tenant cell shows the name when served, full UUID in the tooltip; null name → shortened UUID', async () => {
    stubRuns()
    renderAs(PLATFORM, <IngestionRuns />)
    const table = await screen.findByRole('table')
    // Named tenant → the real name renders (not the UUID tail); the full UUID is the cell tooltip.
    const nameCell = within(table).getByText('Buc-ees')
    expect(nameCell).toBeInTheDocument()
    expect(nameCell.closest('td')).toHaveAttribute('title', A)
    // Un-named tenant → honest fallback to the shortened UUID (never fabricated).
    expect(within(table).getByText(B_SHORT)).toBeInTheDocument()
    // The named tenant's UUID tail is NOT shown as the label (the name replaced it).
    expect(within(table).queryByText(A_SHORT)).toBeNull()
  })

  it('tenant filter OPTION shows the name but its VALUE stays the tenant_id (filter logic unchanged)', async () => {
    stubRuns()
    renderAs(PLATFORM, <IngestionRuns />)
    await screen.findByRole('table')
    const opt = (await screen.findByRole('option', { name: 'Buc-ees' })) as HTMLOptionElement
    expect(opt.value).toBe(A) // VALUE is the tenant_id, not the name
    // Selecting it narrows to the named tenant's row (value-based filtering, unchanged).
    await userEvent.setup().selectOptions(screen.getByLabelText('Tenant'), A)
    const table = screen.getByRole('table')
    expect(within(table).getByText('Buc-ees')).toBeInTheDocument()
    expect(within(table).queryByText(B_SHORT)).toBeNull()
  })
})
