import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { afterEach, vi } from 'vitest'

import type { AuthSnapshot } from '../auth/AuthSnapshot'
import { AuthContext } from '../auth/context'
import type { AuthContextValue } from '../auth/context'
import { writeToken } from '../auth/storage'
import type { RunRow } from '../lib/dis-ui-server/runs'
import { Dashboard } from './Dashboard'

// Fixture-mode render (no backend): the newly-wired Dashboard L2 sections —
//  - Sources connected KPI from metrics.sources_connected (real field),
//  - Recent ingestion runs card from a bounded slice of useRuns (GET /runs shape),
// while Needs attention + Freshness stay marked-pending (L1). The L3 KPI row (rows ingested,
// quality pass rate) must not regress.

const TENANT: AuthSnapshot = {
  userId: 'u_acmeuser0001',
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

function renderDashboard(snapshot: AuthSnapshot = TENANT): void {
  const authValue: AuthContextValue = {
    profile: null,
    status: 'authenticated',
    snapshot,
    login: () => Promise.resolve(),
    logout: () => {},
  }
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const tree: ReactNode = (
    <QueryClientProvider client={qc}>
      <AuthContext.Provider value={authValue}>
        <MemoryRouter initialEntries={['/']}>
          <Dashboard />
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>
  )
  render(tree)
}

describe('Dashboard L2 wiring (fixture mode)', () => {
  it('shows the real Sources connected KPI value', async () => {
    renderDashboard()
    const kpi = (await screen.findByText('Sources connected')).closest('.kpi')
    expect(kpi).not.toBeNull()
    // fixture metrics.sources_connected = 4 (not the old template-count placeholder); await the
    // async query settling the KPI value from its "—" pending state.
    expect(await within(kpi as HTMLElement).findByText('4')).toBeInTheDocument()
    // L3 KPIs not regressed.
    expect(screen.getByText('Rows ingested')).toBeInTheDocument()
    expect(screen.getByText('Quality pass rate')).toBeInTheDocument()
  })

  it('wires Recent ingestion runs to real accepted/quarantined (2-way), honest "—" for non-terminal', async () => {
    renderDashboard()
    // await the runs query settling a real row, then scope assertions to the recent-runs card.
    await screen.findByText('clover_prices')
    const card = (screen.getByRole('heading', { name: 'Recent ingestion runs' }).closest('.card')) as HTMLElement
    const c = within(card)
    // View-all links to the Ingestion Runs surface (scoped to this card — the Needs-attention card
    // now has its own "View all" too).
    expect(c.getByRole('link', { name: 'View all' })).toHaveAttribute('href', '/ingestion-runs')
    // 2-way column (the dropped 3-way Acc/Rev/Rej split is gone). Scope the "no 3-way" check to the
    // column headers so it doesn't match the "Reverse API" method label in a data cell.
    expect(c.getByRole('columnheader', { name: 'Accepted / quarantined' })).toBeInTheDocument()
    expect(c.queryByText('Acc / Rev / Rej')).toBeNull()
    expect(c.queryByRole('columnheader', { name: /rev|reject/i })).toBeNull()
    // real run rows.
    expect(c.getAllByText('Manual CSV').length).toBeGreaterThan(0)
    expect(c.getAllByText('succeeded').length).toBeGreaterThan(0)
    // real terminal counts from the fixture (accepted 1,247 on a succeeded csv run; quarantined 512).
    expect(c.getAllByText('1,247').length).toBeGreaterThan(0)
    expect(c.getByText('512')).toBeInTheDocument()
    // honest "—" for a null count (the failed run's quarantined + the processing run's both).
    expect(c.getAllByText('—').length).toBeGreaterThan(0)
  })

  it('wires Needs attention to the derived feed (no "not available yet" placeholder)', async () => {
    renderDashboard()
    const card = (await screen.findByRole('heading', { name: 'Needs attention' })).closest('.card') as HTMLElement
    // The old placeholder is gone — the feature is available now.
    expect(within(card).queryByText('Not available yet')).toBeNull()
    expect(within(card).queryByText(/Alerts aren’t available yet/)).toBeNull()
    // The card carries a "View all" deep-link to the full Needs attention surface.
    expect(within(card).getByRole('link', { name: 'View all' })).toHaveAttribute('href', '/notifications')
    // Derived items render (the fixtures include failing/stale sources → attention items with badges).
    const failed = await within(card).findByText('Run failed')
    expect(failed).toBeInTheDocument()
    // Each row deep-links to the relevant surface (a failed run → the Ingestion Runs surface).
    expect(failed.closest('a')).toHaveAttribute('href', '/ingestion-runs')
  })
})

// ---- Real mode (fetch spy): the recent-runs card reads /runs + renders live accepted/quarantined ----

function runRow(over: Partial<RunRow> & Pick<RunRow, 'id' | 'source_id'>): RunRow {
  return {
    trace_id: '0190ac0e-1a01-7001-8a01-0000000000e1',
    tenant_id: '0190ac10-1a01-7001-8a01-0000000000a1',
    store_id: null,
    store_name: null,
    source_name: null,
    template_id: null,
    template_name: null,
    method: 'csv_upload',
    status: 'succeeded',
    mapping_version: 1,
    seen_before: false,
    source_payload_id: null,
    file_name: null,
    input_row_count: 500,
    accepted: 500,
    quarantined: 0,
    received_at: '2026-07-14T10:00:00Z',
    published_at: '2026-07-14T10:00:01Z',
    completed_at: '2026-07-14T10:00:02Z',
    ...over,
  }
}

describe('Dashboard recent-runs — real mode (fetch spy)', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.restoreAllMocks()
    localStorage.clear()
  })

  it('reads /runs and renders live accepted/quarantined (not hardcoded "—")', async () => {
    vi.stubEnv('VITE_DIS_UI_SERVER_MODE', 'real')
    writeToken('stub.session.token')
    const calls: string[] = []
    const fetchSpy = vi.fn(async (input: unknown) => {
      const url = String(input)
      calls.push(url)
      if (url.includes('/runs')) {
        return new Response(
          JSON.stringify({
            items: [
              runRow({ id: 'r1', source_id: 'live_a', accepted: 731, quarantined: 4 }),
              runRow({ id: 'r2', source_id: 'live_b', status: 'processing', accepted: null, quarantined: null }),
            ],
            next_cursor: null,
          }),
          { status: 200 },
        )
      }
      if (url.includes('/dashboard/metrics')) {
        return new Response(
          JSON.stringify({
            rows_ingested_24h: 731,
            quarantine_24h: { quarantined_rows: 4, received_rows: 731, rate: 4 / 731 },
            records_in_canonical: { total: 10, by_table: [] },
            flow: [],
            sources_connected: 2,
          }),
          { status: 200 },
        )
      }
      // Needs-attention feed sources (the card now derives from these too) — proper wire shapes.
      if (url.includes('/quarantine')) {
        return new Response(JSON.stringify({ items: [], open_count: 0 }), { status: 200 })
      }
      if (url.includes('/connector-health') || url.includes('/audit')) {
        return new Response(JSON.stringify({ items: [] }), { status: 200 })
      }
      // mapping-templates / template-types: empty is fine for the Flow table.
      return new Response(JSON.stringify([]), { status: 200 })
    })
    vi.stubGlobal('fetch', fetchSpy)

    const authValue: AuthContextValue = {
      profile: null,
      status: 'authenticated',
      snapshot: TENANT,
      login: () => Promise.resolve(),
      logout: () => {},
    }
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <AuthContext.Provider value={authValue}>
          <MemoryRouter initialEntries={['/']}>
            <Dashboard />
          </MemoryRouter>
        </AuthContext.Provider>
      </QueryClientProvider>,
    )

    await screen.findByText('live_a')
    expect(calls.some((u) => u.includes('/api/v1/runs'))).toBe(true)
    const card = screen.getByRole('heading', { name: 'Recent ingestion runs' }).closest('.card') as HTMLElement
    const c = within(card)
    // live accepted/quarantined render (not the old hardcoded "—").
    expect(c.getByText('731')).toBeInTheDocument()
    expect(c.getByText('4')).toBeInTheDocument()
    // the processing run's null counts render honest "—".
    expect(c.getAllByText('—').length).toBeGreaterThan(0)
  })
})

// Chunk 5: honest scope labeling on the KPI header — same endpoint, scope-driven values; we only
// LABEL the scope via the shared isOps discriminator. Values are the SAME fixture numbers for both
// tokens (the fixture getter ignores the token), proving labeling-only, no data change.
describe('Dashboard scope labeling (Chunk 5)', () => {
  it('TENANT token → own-scope label, values unchanged', async () => {
    renderDashboard(TENANT)
    expect(await screen.findByText('Metrics for your tenant.')).toBeInTheDocument()
    expect(screen.queryByText('Fleet-wide metrics across all tenants.')).not.toBeInTheDocument()
    // Sources connected value is the fixture number (4) — unchanged by the labeling.
    const kpi = (await screen.findByText('Sources connected')).closest('.kpi') as HTMLElement
    expect(await within(kpi).findByText('4')).toBeInTheDocument()
  })

  it('PLATFORM token → fleet/all-tenant label, SAME values (labeling only, no breakdown)', async () => {
    renderDashboard(PLATFORM)
    expect(await screen.findByText('Fleet-wide metrics across all tenants.')).toBeInTheDocument()
    expect(screen.queryByText('Metrics for your tenant.')).not.toBeInTheDocument()
    // Identical fixture value (4) — PLATFORM sees the same fleet totals, just labeled fleet-wide.
    // The Chunk 5 labeling + KPI values are unchanged by Chunk 6b (which ADDS the breakdown below).
    const kpi = (await screen.findByText('Sources connected')).closest('.kpi') as HTMLElement
    expect(await within(kpi).findByText('4')).toBeInTheDocument()
    // Chunk 6b: PLATFORM now ALSO renders the per-tenant breakdown below the fleet totals.
    expect(screen.getByRole('heading', { name: 'By tenant' })).toBeInTheDocument()
  })
})

// Chunk 6b: the per-tenant breakdown table (consumes metrics.by_tenant). Fixture by_tenant = 3
// tenants (…a1 rows 1000, …b2 rows 247, …c3 rows 0 with a NULL rate) summing to the fleet totals.
describe('Dashboard by-tenant breakdown (Chunk 6b)', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.restoreAllMocks()
    localStorage.clear()
  })

  const A = '…0000000000a1'
  const B = '…0000000000b2'
  const C = '…0000000000c3'

  function byTenantCard(): HTMLElement {
    return screen.getByRole('heading', { name: 'By tenant' }).closest('.card') as HTMLElement
  }
  function rowOrder(): (string | null)[] {
    return within(byTenantCard())
      .getAllByRole('row')
      .slice(1) // drop the header row
      .map((r) => within(r).getAllByRole('cell')[0].textContent)
  }

  it('PLATFORM renders a row per by_tenant entry, tenant as a shortened UUID (no fabricated name)', async () => {
    renderDashboard(PLATFORM)
    expect(await screen.findByRole('heading', { name: 'By tenant' })).toBeInTheDocument()
    await within(byTenantCard()).findByText(A) // wait for the metrics query to settle the rows
    const card = within(byTenantCard())
    // Columns.
    expect(card.getByRole('columnheader', { name: 'Tenant' })).toBeInTheDocument()
    expect(card.getByRole('columnheader', { name: /Rows ingested/ })).toBeInTheDocument()
    expect(card.getByRole('columnheader', { name: /Quarantined/ })).toBeInTheDocument()
    expect(card.getByRole('columnheader', { name: /Quarantine rate/ })).toBeInTheDocument()
    // One row per by_tenant entry (3), each labelled by the shortened UUID tail, full id in tooltip.
    expect(rowOrder()).toHaveLength(3)
    expect(card.getByText(A)).toBeInTheDocument()
    expect(card.getByText(A).closest('td')).toHaveAttribute('title', '0190ac10-1a01-7001-8a01-0000000000a1')
    expect(card.getByText(B)).toBeInTheDocument()
    expect(card.getByText(C)).toBeInTheDocument()
    // Real per-tenant numbers.
    expect(card.getByText('1,000')).toBeInTheDocument()
    expect(card.getByText('247')).toBeInTheDocument()
  })

  it('renders a null rate (received==0) honestly as "—", never 0% or NaN', async () => {
    renderDashboard(PLATFORM)
    const card = within(byTenantCard())
    // tenant …c3 has received_rows==0 -> null rate -> honest "—"; the other two show a real %.
    expect(await card.findByText('0.20%')).toBeInTheDocument() // …a1: 2/1000
    expect(card.getByText('0.40%')).toBeInTheDocument() // …b2: 1/247
    expect(card.getAllByText('—').length).toBeGreaterThan(0) // …c3 rate
    expect(card.queryByText('NaN')).toBeNull()
    expect(card.queryByText('NaN%')).toBeNull()
  })

  it('sorts by rows (default desc) and by quarantine rate (null sorts last)', async () => {
    renderDashboard(PLATFORM)
    await screen.findByRole('heading', { name: 'By tenant' })
    await within(byTenantCard()).findByText(A) // wait for the metrics query to settle the rows
    // Default sort: rows ingested, descending -> 1000, 247, 0.
    expect(rowOrder()).toEqual([A, B, C])
    // Sort by quarantine rate (desc): 0.40% (…b2) > 0.20% (…a1) > null (…c3, always last).
    await userEvent.setup().click(within(byTenantCard()).getByRole('button', { name: /Quarantine rate/ }))
    expect(rowOrder()).toEqual([B, A, C])
  })

  it('TENANT does NOT render the breakdown (gated on isOps; backend by_tenant is [])', async () => {
    renderDashboard(TENANT)
    // Fleet totals still render (Chunk 5), but no per-tenant section for a TENANT token.
    expect(await screen.findByText('Metrics for your tenant.')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'By tenant' })).toBeNull()
  })

  it('empty by_tenant → honest empty state, section not hidden (real mode, PLATFORM)', async () => {
    vi.stubEnv('VITE_DIS_UI_SERVER_MODE', 'real')
    writeToken('stub.session.token')
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const url = String(input)
        if (url.includes('/dashboard/metrics')) {
          return new Response(
            JSON.stringify({
              rows_ingested_24h: 0,
              quarantine_24h: { quarantined_rows: 0, received_rows: 0, rate: null },
              records_in_canonical: { total: 0, by_table: [] },
              flow: [],
              sources_connected: 0,
              by_tenant: [], // no tenant activity in-window
            }),
            { status: 200 },
          )
        }
        // Needs-attention feed sources (the Dashboard now also derives from these).
        if (url.includes('/quarantine')) {
          return new Response(JSON.stringify({ items: [], open_count: 0 }), { status: 200 })
        }
        if (url.includes('/connector-health') || url.includes('/audit')) {
          return new Response(JSON.stringify({ items: [] }), { status: 200 })
        }
        return new Response(JSON.stringify([]), { status: 200 })
      }),
    )
    const authValue: AuthContextValue = {
      profile: null,
      status: 'authenticated',
      snapshot: PLATFORM,
      login: () => Promise.resolve(),
      logout: () => {},
    }
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <AuthContext.Provider value={authValue}>
          <MemoryRouter initialEntries={['/']}>
            <Dashboard />
          </MemoryRouter>
        </AuthContext.Provider>
      </QueryClientProvider>,
    )
    // The section still renders (heading present) with an honest empty state — not hidden, no table.
    expect(await screen.findByRole('heading', { name: 'No per-tenant activity in the last 24h' })).toBeInTheDocument()
    const card = screen.getByRole('heading', { name: 'By tenant' }).closest('.card') as HTMLElement
    expect(within(card).queryByRole('table')).toBeNull()
  })
})

// The Needs-attention summary card — scope handling + honest empty state (Chunk: wired feed).
describe('Dashboard Needs-attention card — scope + empty', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.restoreAllMocks()
    localStorage.clear()
  })

  function naCard(): HTMLElement {
    return screen.getByRole('heading', { name: 'Needs attention' }).closest('.card') as HTMLElement
  }

  it('TENANT shows the derived items WITHOUT a tenant chip (own scope)', async () => {
    renderDashboard(TENANT)
    const card = within(naCard())
    await card.findByText('Run failed')
    // TENANT is single-tenant scope → no per-item tenant attribution chip (…UUID tail).
    expect(card.queryByText(/…/)).toBeNull()
  })

  it('PLATFORM attributes each item to its owning tenant via the shared tenant-label (…UUID tail)', async () => {
    renderDashboard(PLATFORM)
    const card = within(naCard())
    await card.findByText('Run failed')
    // Fleet scope → the shared tenant-label helper renders the owning tenant (shortened UUID, no
    // fabricated name); Chunk 9's tenant_name would flow through this same helper automatically.
    expect(card.getAllByText(/…/).length).toBeGreaterThan(0)
  })

  it('honest empty state when nothing needs attention (real mode, all sources empty)', async () => {
    vi.stubEnv('VITE_DIS_UI_SERVER_MODE', 'real')
    writeToken('stub.session.token')
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const url = String(input)
        if (url.includes('/runs')) {
          return new Response(JSON.stringify({ items: [], next_cursor: null }), { status: 200 })
        }
        if (url.includes('/dashboard/metrics')) {
          return new Response(
            JSON.stringify({
              rows_ingested_24h: 0,
              quarantine_24h: { quarantined_rows: 0, received_rows: 0, rate: null },
              records_in_canonical: { total: 0, by_table: [] },
              flow: [],
              sources_connected: 0,
              by_tenant: [],
            }),
            { status: 200 },
          )
        }
        if (url.includes('/quarantine')) {
          return new Response(JSON.stringify({ items: [], open_count: 0 }), { status: 200 })
        }
        if (url.includes('/connector-health') || url.includes('/audit')) {
          return new Response(JSON.stringify({ items: [] }), { status: 200 })
        }
        return new Response(JSON.stringify([]), { status: 200 })
      }),
    )
    const authValue: AuthContextValue = {
      profile: null,
      status: 'authenticated',
      snapshot: TENANT,
      login: () => Promise.resolve(),
      logout: () => {},
    }
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <AuthContext.Provider value={authValue}>
          <MemoryRouter initialEntries={['/']}>
            <Dashboard />
          </MemoryRouter>
        </AuthContext.Provider>
      </QueryClientProvider>,
    )
    // Honest empty state — the feature is available; nothing needs attention. NOT "not available yet".
    expect(await within(naCard()).findByText('Nothing needs attention right now')).toBeInTheDocument()
    expect(within(naCard()).queryByText('Not available yet')).toBeNull()
  })
})

// Chunk 9-FE: the Dashboard consumes tenant_name — the by-tenant table AND the Needs-attention card
// attribution show the NAME (UUID in tooltip), falling back to the UUID when the name is null.
describe('Dashboard tenant_name display (Chunk 9-FE, real mode PLATFORM)', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.restoreAllMocks()
    localStorage.clear()
  })

  const A = '0190ac10-1a01-7001-8a01-0000000000a1'
  const B = '0190ac10-1a01-7001-8a01-0000000000b2'

  it('by-tenant table shows the name (UUID tooltip); a null name falls back to the UUID tail', async () => {
    vi.stubEnv('VITE_DIS_UI_SERVER_MODE', 'real')
    writeToken('stub.session.token')
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const url = String(input)
        if (url.includes('/dashboard/metrics')) {
          return new Response(
            JSON.stringify({
              rows_ingested_24h: 1000,
              quarantine_24h: { quarantined_rows: 2, received_rows: 1000, rate: 2 / 1000 },
              records_in_canonical: { total: 0, by_table: [] },
              flow: [],
              sources_connected: 0,
              by_tenant: [
                { tenant_id: A, tenant_name: 'Buc-ees', rows_ingested_24h: 800, quarantine_24h: { quarantined_rows: 2, received_rows: 800, rate: 2 / 800 } },
                { tenant_id: B, tenant_name: null, rows_ingested_24h: 200, quarantine_24h: { quarantined_rows: 0, received_rows: 200, rate: 0 } },
              ],
            }),
            { status: 200 },
          )
        }
        if (url.includes('/runs')) return new Response(JSON.stringify({ items: [], next_cursor: null }), { status: 200 })
        if (url.includes('/quarantine')) return new Response(JSON.stringify({ items: [], open_count: 0 }), { status: 200 })
        if (url.includes('/connector-health') || url.includes('/audit')) return new Response(JSON.stringify({ items: [] }), { status: 200 })
        return new Response(JSON.stringify([]), { status: 200 })
      }),
    )
    const authValue: AuthContextValue = { profile: null, status: 'authenticated', snapshot: PLATFORM, login: () => Promise.resolve(), logout: () => {} }
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <AuthContext.Provider value={authValue}>
          <MemoryRouter initialEntries={['/']}><Dashboard /></MemoryRouter>
        </AuthContext.Provider>
      </QueryClientProvider>,
    )
    const card = (await screen.findByRole('heading', { name: 'By tenant' })).closest('.card') as HTMLElement
    const named = await within(card).findByText('Buc-ees')
    expect(named.closest('td')).toHaveAttribute('title', A) // full UUID tooltip
    // null tenant_name → shortened UUID fallback (…b2), never fabricated.
    expect(within(card).getByText('…0000000000b2')).toBeInTheDocument()
  })

  it('Needs-attention card attributes each item to its tenant by NAME (UUID tooltip)', async () => {
    vi.stubEnv('VITE_DIS_UI_SERVER_MODE', 'real')
    writeToken('stub.session.token')
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const url = String(input)
        if (url.includes('/runs')) {
          return new Response(
            JSON.stringify({
              items: [runRow({ id: 'rf', source_id: 'src_a', status: 'failed', tenant_id: A, tenant_name: 'Buc-ees', accepted: null, quarantined: null })],
              next_cursor: null,
            }),
            { status: 200 },
          )
        }
        if (url.includes('/dashboard/metrics')) {
          return new Response(JSON.stringify({ rows_ingested_24h: 0, quarantine_24h: { quarantined_rows: 0, received_rows: 0, rate: null }, records_in_canonical: { total: 0, by_table: [] }, flow: [], sources_connected: 0, by_tenant: [] }), { status: 200 })
        }
        if (url.includes('/quarantine')) return new Response(JSON.stringify({ items: [], open_count: 0 }), { status: 200 })
        if (url.includes('/connector-health') || url.includes('/audit')) return new Response(JSON.stringify({ items: [] }), { status: 200 })
        return new Response(JSON.stringify([]), { status: 200 })
      }),
    )
    const authValue: AuthContextValue = { profile: null, status: 'authenticated', snapshot: PLATFORM, login: () => Promise.resolve(), logout: () => {} }
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <AuthContext.Provider value={authValue}>
          <MemoryRouter initialEntries={['/']}><Dashboard /></MemoryRouter>
        </AuthContext.Provider>
      </QueryClientProvider>,
    )
    const card = (await screen.findByRole('heading', { name: 'Needs attention' })).closest('.card') as HTMLElement
    await within(card).findByText('Run failed')
    // The item's tenant attribution shows the NAME, with the full UUID in the tooltip.
    const attr = within(card).getByTitle(A)
    expect(attr.textContent).toContain('Buc-ees')
  })
})
