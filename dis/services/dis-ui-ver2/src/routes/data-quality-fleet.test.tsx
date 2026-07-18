import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { AuthSnapshot } from '../auth/AuthSnapshot'
import { AuthContext } from '../auth/context'
import type { AuthContextValue } from '../auth/context'
import { writeToken } from '../auth/storage'
import { DataQuality } from './DataQuality'

// Chunk 4: PLATFORM fleet quarantine — the REAL see-all endpoint + a read-only, filterable triage
// table attributed by tenant_id. Fixtures: 3 open rows — tenant A (canonical-shape), tenant B
// (normalization), tenant A (source-shape).
const A_SHORT = '…0000000000a1'
const B_SHORT = '…0000000000b2'

const TENANT: AuthSnapshot = { userId: 'u', tenantId: 't_acme9k2l1mn4', storeId: 's', userType: 'TENANT', roles: ['dis:read'] }
const PLATFORM: AuthSnapshot = { userId: 'anjali', tenantId: null, storeId: null, userType: 'PLATFORM', roles: ['dis:ops', 'dis:read'] }

function renderAs(snapshot: AuthSnapshot) {
  const authValue: AuthContextValue = { status: 'authenticated', snapshot, login: () => Promise.resolve(), logout: () => {} }
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <AuthContext.Provider value={authValue}>
        <MemoryRouter>
          <DataQuality />
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.unstubAllEnvs()
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('Data Quality — PLATFORM fleet quarantine (read-only triage)', () => {
  it('PLATFORM in REAL mode FETCHES the real /quarantine endpoint (not a PendingState)', async () => {
    vi.stubEnv('VITE_DIS_UI_SERVER_MODE', 'real')
    writeToken('stub.session.token')
    const fetchSpy: ReturnType<typeof vi.fn> = vi.fn(async () => new Response('{"items":[],"open_count":0}', { status: 200 }))
    vi.stubGlobal('fetch', fetchSpy)
    renderAs(PLATFORM)
    await vi.waitFor(() => expect(fetchSpy).toHaveBeenCalled())
    expect(String(fetchSpy.mock.calls[0][0])).toContain('/api/v1/quarantine')
    expect(screen.queryByRole('heading', { name: 'Fleet quarantine pending' })).toBeNull()
  })

  it('renders a fleet table with a Tenant column (shortened UUID, full tooltip, no fabricated name)', async () => {
    renderAs(PLATFORM)
    expect(await screen.findByRole('heading', { name: 'Fleet quarantine' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Tenant' })).toBeInTheDocument()
    const table = screen.getByRole('table')
    expect(within(table).getAllByText(A_SHORT).length).toBeGreaterThan(0)
    expect(within(table).getAllByText(B_SHORT).length).toBeGreaterThan(0)
    // Full UUID is available in the cell tooltip, not a fabricated friendly name.
    expect(within(table).getAllByTitle('0190ac10-1a01-7001-8a01-0000000000a1').length).toBeGreaterThan(0)
  })

  it('tenant + failure-type filters auto-populate, narrow, and combine (AND); clear-all resets', async () => {
    renderAs(PLATFORM)
    await screen.findByRole('heading', { name: 'Fleet quarantine' })
    const user = userEvent.setup()
    const tenantSel = screen.getByLabelText('Tenant') as HTMLSelectElement
    const typeSel = screen.getByLabelText('Failure type') as HTMLSelectElement
    // Auto-populated from the rows present.
    expect([...tenantSel.options].map((o) => o.textContent)).toEqual(expect.arrayContaining([A_SHORT, B_SHORT]))
    expect([...typeSel.options].map((o) => o.textContent)).toEqual(
      expect.arrayContaining(['canonical-shape', 'normalization', 'source-shape']),
    )
    // Tenant B narrows to B only.
    await user.selectOptions(tenantSel, screen.getByRole('option', { name: B_SHORT }))
    expect(within(screen.getByRole('table')).queryAllByText(A_SHORT).length).toBe(0)
    // Clear all resets to the full fleet.
    await user.click(screen.getByRole('button', { name: 'Clear all' }))
    expect(within(screen.getByRole('table')).getAllByText(A_SHORT).length).toBeGreaterThan(0)
  })

  it('a no-match filter combination (tenant A AND normalization) → honest empty state', async () => {
    renderAs(PLATFORM)
    await screen.findByRole('heading', { name: 'Fleet quarantine' })
    const user = userEvent.setup()
    await user.selectOptions(screen.getByLabelText('Tenant'), screen.getByRole('option', { name: A_SHORT }))
    await user.selectOptions(screen.getByLabelText('Failure type'), screen.getByRole('option', { name: 'normalization' }))
    expect(screen.getByText('No items match these filters')).toBeInTheDocument()
    expect(screen.queryByRole('table')).toBeNull()
  })

  it('is READ-ONLY: NO resubmit/resolve/dismiss control in the fleet view or its drill-in drawer', async () => {
    renderAs(PLATFORM)
    await screen.findByRole('heading', { name: 'Fleet quarantine' })
    // No mutate control anywhere in the fleet view.
    expect(screen.queryByRole('button', { name: /Mark resolved|Dismiss|Resubmit/i })).toBeNull()
    // Open the read-only drill-in; still no mutate control.
    await userEvent.setup().click(screen.getAllByRole('row').slice(1)[0])
    expect(await screen.findByRole('dialog', { name: 'Quarantine detail' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Mark resolved|Dismiss|Resubmit/i })).toBeNull()
  })
})

describe('Data Quality — TENANT view unchanged', () => {
  it('TENANT renders its per-tenant view (no Tenant column) and its detail keeps the (inert) Resolve/Dismiss', async () => {
    renderAs(TENANT)
    expect(await screen.findByRole('heading', { name: 'Quarantined rows' })).toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: 'Tenant' })).toBeNull()
    expect(screen.queryByLabelText('Failure type')).toBeNull() // no fleet filter bar
    // The tenant detail drawer still shows the inert mutate actions (fleet-only omission proven).
    await userEvent.setup().click(screen.getAllByRole('row').slice(1)[0])
    await screen.findByRole('dialog', { name: 'Quarantine detail' })
    expect(screen.getByRole('button', { name: 'Mark resolved' })).toBeInTheDocument()
  })
})
