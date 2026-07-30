import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { writeToken } from '../auth/storage'
import type { AuthSnapshot } from '../auth/AuthSnapshot'
import { AuthContext } from '../auth/context'
import type { AuthContextValue } from '../auth/context'
import type { ConnectorHealthRow } from '../lib/dis-ui-server/connector-health'
import { ConnectorHealth } from './ConnectorHealth'

const TENANT: AuthSnapshot = {
  userId: 'u_acmeuser0001',
  tenantId: 't_acme9k2l1mn4',
  storeId: 's_x',
  userType: 'TENANT',
  roles: ['dis:read'],
}

const KEY = ['dis-ui-server', 'connector-health', TENANT.tenantId]

function row(over: Partial<ConnectorHealthRow>): ConnectorHealthRow {
  return {
    tenant_id: '0190ac10-1a01-7001-8a01-0000000000a1',
    source_id: 'src',
    display_name: 'Src',
    channel: 'csv_upload',
    heartbeat_label: null,
    status: 'healthy',
    last_seen_at: new Date(Date.now() - 2 * 60_000).toISOString(),
    last_error_at: null,
    last_error_detail: null,
    auth_expires_at: null,
    rate_limit_state: null,
    missed_intervals: null,
    ...over,
  }
}

// A row of each status so the KPI rollup + badge/dot mapping are all exercised.
const ROWS: ConnectorHealthRow[] = [
  row({ source_id: 'csv', display_name: 'Manual CSV Upload', channel: 'csv_upload', status: 'healthy' }),
  row({ source_id: 'api_stale', display_name: 'Shopify POS', channel: 'api', status: 'stale' }),
  row({
    source_id: 'rev',
    display_name: 'Square Orders',
    channel: 'reverse_api',
    status: 'auth_expiring',
    auth_expires_at: new Date(Date.now() + 4 * 86_400_000).toISOString(),
  }),
  row({
    source_id: 'api_rl',
    display_name: 'Competitor Feed',
    channel: 'api',
    status: 'rate_limited',
    rate_limit_state: '429s at 18%',
  }),
  row({
    source_id: 'erp',
    display_name: 'ERP Nightly Prices',
    channel: 'csv_erp',
    status: 'pending',
    last_seen_at: null,
  }),
]

function renderGrid(rows: ConnectorHealthRow[] = ROWS) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  qc.setQueryData(KEY, { items: rows })
  const authValue: AuthContextValue = {
    profile: null,
    status: 'authenticated',
    snapshot: TENANT,
    login: () => Promise.resolve(),
    logout: () => {},
  }
  const Wrap = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>
      <AuthContext.Provider value={authValue}>
        <MemoryRouter>{children}</MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>
  )
  return render(
    <Wrap>
      <ConnectorHealth />
    </Wrap>,
  )
}

describe('Connector Health card grid', () => {
  it('renders one card per connector with its status badge label', () => {
    const { container } = renderGrid()
    // Scope to the grid: the status labels ALSO appear as Status-filter <option>s, so a bare
    // getByText would match twice.
    const grid = within(container.querySelector('.grid') as HTMLElement)
    expect(grid.getByText('Manual CSV Upload')).toBeInTheDocument()
    expect(grid.getByText('Healthy')).toBeInTheDocument()
    expect(grid.getByText('Stale - escalated')).toBeInTheDocument()
    expect(grid.getByText('Auth expiring')).toBeInTheDocument()
    expect(grid.getByText('Rate limited')).toBeInTheDocument()
    expect(grid.getByText('Receiver pending')).toBeInTheDocument()
  })

  it('maps status to the dot class', () => {
    const { container } = renderGrid()
    expect(container.querySelector('.dot.d-ok')).not.toBeNull() // healthy
    expect(container.querySelector('.dot.d-fail')).not.toBeNull() // stale
    expect(container.querySelector('.dot.d-warn')).not.toBeNull() // auth_expiring / rate_limited
    expect(container.querySelector('.dot.d-mut')).not.toBeNull() // pending
  })

  it('KPI counts exclude pending (a no-producer connector is not healthy)', () => {
    renderGrid()
    expect(screen.getByText('1 stale')).toBeInTheDocument()
    expect(screen.getByText('2 attention')).toBeInTheDocument() // auth_expiring + rate_limited
    expect(screen.getByText('1 healthy')).toBeInTheDocument() // NOT 2 — pending is not folded in
    expect(screen.getByText('1 pending')).toBeInTheDocument() // shown separately, muted
  })

  it('renders honest "—" for fields the wire does not carry (CSV: auth/rate/missed null)', () => {
    renderGrid([
      row({ source_id: 'csv', display_name: 'Manual CSV Upload', channel: 'csv_upload', heartbeat_label: 'on upload' }),
    ])
    const card = screen.getByText('Manual CSV Upload').closest('.card') as HTMLElement
    const scoped = within(card)
    // Last seen is real (relative), Heartbeat is the label — NOT dashes.
    expect(scoped.getByText(/ago$/)).toBeInTheDocument()
    expect(scoped.getByText('on upload')).toBeInTheDocument()
    // Missed intervals / Auth expiry / Rate limit are null → exactly three "—".
    expect(scoped.getAllByText('—')).toHaveLength(3)
  })

  it('renders "—" for last seen + all 5 fields on a pending (no-producer) connector', () => {
    renderGrid([row({ source_id: 'erp', display_name: 'ERP', channel: 'csv_erp', status: 'pending', last_seen_at: null, heartbeat_label: null })])
    const card = screen.getByText('ERP').closest('.card') as HTMLElement
    // Last seen, Heartbeat, Missed, Auth, Rate = 5 dashes.
    expect(within(card).getAllByText('—')).toHaveLength(5)
  })

  it('maps channel to the method chip label; null → "—"', () => {
    renderGrid([
      row({ source_id: 'a', display_name: 'A', channel: 'csv_upload' }),
      row({ source_id: 'b', display_name: 'B', channel: 'api' }),
      row({ source_id: 'c', display_name: 'C', channel: 'reverse_api' }),
      row({ source_id: 'd', display_name: 'D', channel: 'csv_erp' }),
      row({ source_id: 'e', display_name: 'E', channel: null }),
    ])
    // Method labels ALSO appear as Method-filter <option>s, so assert the chip WITHIN each card.
    const chip = (name: string, label: string) => {
      const card = screen.getByText(name).closest('.card') as HTMLElement
      expect(within(card).getByText(label, { selector: '.method' })).toBeInTheDocument()
    }
    chip('A', 'Manual CSV')
    chip('B', 'API pull')
    chip('C', 'Reverse API')
    chip('D', 'ERP CSV')
    chip('E', '—') // channel null → method chip "—"
  })

  it('empty state when there are no connectors', () => {
    renderGrid([])
    expect(screen.getByText('No connectors')).toBeInTheDocument()
  })
})

// REAL MODE: the surface must fire the live GET /api/v1/connector-health (not the fixture) and
// render whatever the wire returns, honestly. A live backend is not reachable in jsdom, so we spy
// on fetch — the assertions are (a) the exact URL requested, (b) the honest render of the payload.
describe('Connector Health — real mode (fetch spy)', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.restoreAllMocks()
    localStorage.clear()
  })

  const req = { url: '' } // captures the URL the surface requested

  function renderRealMode(payload: { items: ConnectorHealthRow[] }) {
    vi.stubEnv('VITE_DIS_UI_SERVER_MODE', 'real')
    writeToken('stub.session.token') // client sessionToken() requires a stored token
    const fetchSpy = vi.fn(async (input: unknown) => {
      req.url = String(input)
      return new Response(JSON.stringify(payload), { status: 200 })
    })
    vi.stubGlobal('fetch', fetchSpy)
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const authValue: AuthContextValue = {
      profile: null,
      status: 'authenticated',
      snapshot: TENANT,
      login: () => Promise.resolve(),
      logout: () => {},
    }
    render(
      <QueryClientProvider client={qc}>
        <AuthContext.Provider value={authValue}>
          <MemoryRouter>
            <ConnectorHealth />
          </MemoryRouter>
        </AuthContext.Provider>
      </QueryClientProvider>,
    )
    return fetchSpy
  }

  it('fires GET /api/v1/connector-health and renders the wire honestly', async () => {
    const fetchSpy = renderRealMode({
      items: [
        row({
          source_id: 'manual_csv_upload',
          display_name: 'Manual CSV Upload',
          channel: 'csv_upload',
          heartbeat_label: 'on upload',
          status: 'healthy',
          last_seen_at: new Date(Date.now() - 3 * 60_000).toISOString(),
          auth_expires_at: null, // CSV: no producer sets these → "—"
          rate_limit_state: null,
          missed_intervals: null,
        }),
        row({
          source_id: 'erp_nightly',
          display_name: 'ERP Nightly',
          channel: 'csv_erp',
          status: 'pending',
          last_seen_at: null,
          heartbeat_label: null,
        }),
      ],
    })
    // The active CSV connector renders with a real last_seen and honest dashes.
    const card = (await screen.findByText('Manual CSV Upload')).closest('.card') as HTMLElement
    await vi.waitFor(() => expect(fetchSpy).toHaveBeenCalled())
    expect(req.url).toContain('/api/v1/connector-health')
    // Connector Health is now a normal available surface (no longer premium-locked): the live
    // fetch fires and the real data renders directly, with no lock banner / faded content region.
    expect(screen.queryByText('Connector Health is a premium feature')).toBeNull()
    expect(card.closest('.premium-lock__content')).toBeNull()
    expect(within(card).getByText(/ago$/)).toBeInTheDocument() // real last_seen
    expect(within(card).getAllByText('—')).toHaveLength(3) // missed/auth/rate null
    // The no-producer connector is pending (badge) with all 5 fields "—".
    const erp = screen.getByText('ERP Nightly').closest('.card') as HTMLElement
    expect(within(erp).getByText('Receiver pending')).toBeInTheDocument()
    expect(within(erp).getAllByText('—')).toHaveLength(5)
  })
})
