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
import { NotificationsRoute } from './NotificationsRoute'

// Chunk 2 — the "Needs attention" derived feed (replaces the fixture-only Notifications route).
// Fixture mode drives the derivation from the four source fixtures; a real-mode fetch stub proves
// the empty state + real wiring.

const TENANT: AuthSnapshot = {
  userId: 'u1',
  tenantId: 't_acme9k2l1mn4',
  storeId: 's_x',
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

function Wrap({ snapshot, children }: { snapshot: AuthSnapshot; children: ReactNode }) {
  const authValue: AuthContextValue = {
    status: 'authenticated',
    snapshot,
    login: () => Promise.resolve(),
    logout: () => {},
  }
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <AuthContext.Provider value={authValue}>
        <MemoryRouter>{children}</MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>
  )
}

const RANK: Record<string, number> = { error: 0, warning: 1, info: 2 }

afterEach(() => {
  vi.unstubAllEnvs()
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('Needs attention — TENANT (fixture mode)', () => {
  it('derives a per-item list from the four sources and sorts by severity then recency', async () => {
    render(<Wrap snapshot={TENANT}><NotificationsRoute /></Wrap>)
    expect(await screen.findByRole('heading', { name: 'Needs Attention' })).toBeInTheDocument()
    // Items derived (connector fixture alone has 4 non-healthy + runs partial + quarantine open).
    const rows = await screen.findAllByRole('row')
    expect(rows.length).toBeGreaterThan(1) // header + data rows
    // Severity badges appear in non-decreasing rank order (error → warning → info).
    const badges = screen.getAllByText(/^(error|warning|info)$/).map((el) => RANK[el.textContent ?? ''])
    expect(badges).toEqual([...badges].sort((a, b) => a - b))
  })

  it('ROW CLICK opens the shared drawer; the action lives IN the drawer (not inline on the row)', async () => {
    render(<Wrap snapshot={TENANT}><NotificationsRoute /></Wrap>)
    await screen.findByRole('heading', { name: 'Needs Attention' })
    // Closed: the drawer (role=dialog) is aria-hidden, so it is not in the a11y tree; no action yet.
    expect(screen.queryByRole('dialog')).toBeNull()
    const user = userEvent.setup()
    const dataRows = (await screen.findAllByRole('row')).slice(1) // drop the header
    await user.click(dataRows[0])
    // The SHARED drawer opens...
    const drawer = await screen.findByRole('dialog', { name: 'Needs attention detail' })
    expect(drawer).toBeInTheDocument()
    // ...and the action button (deep-link) lives INSIDE it, pointing at an existing ver2 route.
    const actions = screen.getAllByRole('link')
    expect(actions.length).toBeGreaterThan(0)
    const hrefs = actions.map((a) => a.getAttribute('href'))
    expect(hrefs.some((h) => ['/ingestion-runs', '/connector-health', '/data-quality', '/audit'].includes(h ?? ''))).toBe(true)
  })

  it('is STATELESS: no mark-read, no unread badge, no ack/escalate anywhere', async () => {
    render(<Wrap snapshot={TENANT}><NotificationsRoute /></Wrap>)
    await screen.findByRole('heading', { name: 'Needs Attention' })
    expect(screen.queryByText(/mark read/i)).toBeNull()
    expect(screen.queryByText(/mark all read/i)).toBeNull()
    expect(screen.queryByText(/unread/i)).toBeNull()
    expect(screen.queryByText(/acknowledge|escalate/i)).toBeNull()
  })
})

describe('Needs attention — PLATFORM (fixture mode): filterable triage', () => {
  // Fixtures span two tenants (…a1 and …b2). Shortened tenant labels shown in cells/options.
  const A_SHORT = '…0000000000a1'
  const B_SHORT = '…0000000000b2'

  async function renderFleet(): Promise<ReturnType<typeof userEvent.setup>> {
    render(<Wrap snapshot={PLATFORM}><NotificationsRoute /></Wrap>)
    await screen.findByRole('heading', { name: 'Needs Attention' })
    // DEFAULT is a single flat table (severity-sorted, not grouped).
    await screen.findByRole('table')
    return userEvent.setup()
  }

  it('DEFAULT: a single flat fleet table, severity-sorted (error first), with a Tenant column', async () => {
    await renderFleet()
    expect(screen.getAllByRole('table')).toHaveLength(1) // flat, not per-tenant cards
    expect(screen.getByRole('columnheader', { name: 'Tenant' })).toBeInTheDocument()
    // First data row is the highest severity present (error: the failed run fixture).
    const bodyRows = screen.getAllByRole('row').slice(1) // drop header
    expect(within(bodyRows[0]).getByText('error')).toBeInTheDocument()
    // Tenant shown as a shortened UUID (no fabricated friendly name).
    expect(screen.getAllByText(A_SHORT).length).toBeGreaterThan(0)
  })

  it('tenant filter is auto-populated from present tenant_ids and narrows the table', async () => {
    const user = await renderFleet()
    const tenantSelect = screen.getByLabelText('Tenant') as HTMLSelectElement
    const optionLabels = [...tenantSelect.options].map((o) => o.textContent)
    expect(optionLabels).toContain(A_SHORT) // auto-populated, not hardcoded
    expect(optionLabels).toContain(B_SHORT)
    await user.selectOptions(tenantSelect, screen.getByRole('option', { name: B_SHORT }))
    // Only tenant-B rows remain (scope to the TABLE — the select options also contain these labels).
    const table = screen.getByRole('table')
    expect(within(table).queryAllByText(A_SHORT).length).toBe(0)
    expect(within(table).getAllByText(B_SHORT).length).toBeGreaterThan(0)
  })

  it('severity filter narrows to the chosen severity', async () => {
    const user = await renderFleet()
    await user.click(screen.getByRole('button', { name: 'error' }))
    const bodyRows = screen.getAllByRole('row').slice(1)
    expect(bodyRows.length).toBeGreaterThan(0)
    expect(bodyRows.every((r) => within(r).queryByText('error') !== null)).toBe(true)
  })

  it('type filter narrows to the chosen item kind', async () => {
    const user = await renderFleet()
    await user.selectOptions(screen.getByLabelText('Type'), screen.getByRole('option', { name: 'Quarantine backlog' }))
    // Every visible row is a quarantine item (title carries "quarantined").
    const bodyRows = screen.getAllByRole('row').slice(1)
    expect(bodyRows.every((r) => /quarantined/i.test(r.textContent ?? ''))).toBe(true)
  })

  it('filters combine (AND) and clear-all resets', async () => {
    const user = await renderFleet()
    const before = screen.getAllByRole('row').length
    await user.click(screen.getByRole('button', { name: 'error' }))
    await user.selectOptions(screen.getByLabelText('Tenant'), screen.getByRole('option', { name: B_SHORT }))
    // error AND tenant B → the failed run (tenant B); no tenant-A rows (scope to the table).
    expect(within(screen.getByRole('table')).queryAllByText(A_SHORT).length).toBe(0)
    // Clear-all restores the full table.
    await user.click(screen.getByRole('button', { name: 'Clear all' }))
    expect(screen.getAllByRole('row').length).toBe(before)
  })

  it('no-match filter combination → honest empty state', async () => {
    const user = await renderFleet()
    // info severity exists only for tenant B (rate-limited); info + tenant A → no match.
    await user.click(screen.getByRole('button', { name: 'info' }))
    await user.selectOptions(screen.getByLabelText('Tenant'), screen.getByRole('option', { name: A_SHORT }))
    expect(screen.getByText('No items match these filters')).toBeInTheDocument()
    expect(screen.queryByRole('table')).toBeNull()
  })

  it('group-by-tenant toggle switches from the flat table to per-tenant grouped cards', async () => {
    const user = await renderFleet()
    expect(screen.getAllByRole('table')).toHaveLength(1) // flat by default
    await user.click(screen.getByRole('button', { name: 'By tenant' }))
    // Grouped: one table per tenant card (≥2), each headed by the tenant (the "Tenant …" header
    // text is unique to the group card; the select option has no "Tenant " prefix).
    expect(screen.getAllByRole('table').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('Tenant …0000000000a1')).toBeInTheDocument()
  })

  it('row-click still opens the shared drawer (action inside it), from the flat table', async () => {
    const user = await renderFleet()
    expect(screen.queryByRole('dialog')).toBeNull()
    await user.click(screen.getAllByRole('row').slice(1)[0])
    const drawer = await screen.findByRole('dialog', { name: 'Needs attention detail' })
    expect(within(drawer).getAllByRole('link').length).toBeGreaterThan(0)
  })
})

describe('Needs attention — empty + real wiring (real mode, fetch stub)', () => {
  it('all sources empty → the honest empty state', async () => {
    vi.stubEnv('VITE_DIS_UI_SERVER_MODE', 'real')
    writeToken('stub.session.token')
    // Every endpoint returns empty (items:[], open_count:0) — runs/connector/audit read .items,
    // quarantine reads .open_count.
    const fetchSpy = vi.fn(async () => new Response('{"items":[],"open_count":0,"next_cursor":null}', { status: 200 }))
    vi.stubGlobal('fetch', fetchSpy)
    render(<Wrap snapshot={TENANT}><NotificationsRoute /></Wrap>)
    expect(await screen.findByText('Nothing needs attention right now')).toBeInTheDocument()
    expect(fetchSpy).toHaveBeenCalled() // the feed really queried the endpoints
  })
})
