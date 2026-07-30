import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { AuthSnapshot } from '../auth/AuthSnapshot'
import { AuthContext } from '../auth/context'
import type { AuthContextValue } from '../auth/context'
import { writeToken } from '../auth/storage'
import { DataQuality } from './DataQuality'
import { NotificationsRoute } from './NotificationsRoute'
import { SchemaDrift } from './SchemaDrift'

// Two coupled behaviors under test:
//  A. isOps now keys on user_type -> DataQuality routes TENANT to TenantView, PLATFORM to
//     FleetView (fixture mode proves the routing without a live backend).
//  B. In REAL mode the three L1 fixture-only surfaces render an honest pending state instead of
//     firing a fixture getter that throws (Notifications / SchemaDrift) or is unwired (fleet).

const TENANT: AuthSnapshot = {
  userId: 'u_acmeuser0001',
  tenantId: 't_acme9k2l1mn4',
  storeId: 's_x',
  userType: 'TENANT',
  roles: ['dis:ops', 'dis:read', 'dis:upload'], // carries dis:ops, yet must NOT be treated as ops
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
    profile: null,
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

afterEach(() => {
  vi.unstubAllEnvs()
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('Fix A: DataQuality scope routing keys on user_type (fixture mode)', () => {
  it('TENANT (even with dis:ops role) renders the tenant view, not the fleet view', async () => {
    render(<Wrap snapshot={TENANT}><DataQuality /></Wrap>)
    expect(screen.getByText('Rows that failed validation for your tenant.')).toBeInTheDocument()
    // Tenant quarantine feed (fixture) loads its card, not the cross-tenant fleet card.
    expect(await screen.findByRole('heading', { name: 'Quarantined rows' })).toBeInTheDocument()
    expect(screen.queryByText('Fleet-wide quarantine across all tenants.')).not.toBeInTheDocument()
  })

  it('PLATFORM renders the fleet (cross-tenant) view', async () => {
    render(<Wrap snapshot={PLATFORM}><DataQuality /></Wrap>)
    expect(screen.getByText('Fleet-wide quarantine across all tenants.')).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'Fleet quarantine' })).toBeInTheDocument()
  })
})

describe('Fix B: L1 fixture-only surfaces render pending in real mode', () => {
  function stubRealMode(): void {
    vi.stubEnv('VITE_DIS_UI_SERVER_MODE', 'real')
  }

  // Needs attention (Chunk 2) is now a REAL derived feed — it renders in real mode (no pending
  // short-circuit) and derives from the live endpoints.
  it('Needs attention renders the derived feed in real mode (not the old pending)', () => {
    stubRealMode()
    render(<Wrap snapshot={TENANT}><NotificationsRoute /></Wrap>)
    expect(screen.getByRole('heading', { name: 'Needs Attention' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Not available yet' })).not.toBeInTheDocument()
  })

  // Chunk 4: the PLATFORM fleet view now calls the REAL see-all endpoint (no pending short-circuit).
  // In real mode with no fetch stub the query is in-flight → LoadingState; the old pending is gone.
  it('DataQuality fleet (PLATFORM) takes the real-fetch path in real mode (no pending short-circuit)', () => {
    stubRealMode()
    render(<Wrap snapshot={PLATFORM}><DataQuality /></Wrap>)
    expect(screen.getByText('Loading fleet quarantine…')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Fleet quarantine pending' })).not.toBeInTheDocument()
  })

  it('DataQuality TENANT in real mode still takes the tenant (real-wired) branch, not fleet pending', () => {
    stubRealMode()
    render(<Wrap snapshot={TENANT}><DataQuality /></Wrap>)
    expect(screen.getByText('Rows that failed validation for your tenant.')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Fleet quarantine pending' })).not.toBeInTheDocument()
  })

  it('SchemaDrift (premium-locked) renders under the lock, not the misleading "No shadow run" empty', () => {
    stubRealMode()
    render(<Wrap snapshot={TENANT}><SchemaDrift /></Wrap>)
    expect(screen.getByText('Schema Drift is a premium feature')).toBeInTheDocument()
    expect(screen.queryByText('No shadow run')).not.toBeInTheDocument()
  })
})

// Real-mode wire evidence: prove the branches issue (or suppress) the right HTTP call. A live
// backend is not reachable here, so we spy on fetch — the assertion is which URL is requested,
// not the response. TENANT DataQuality must hit the real tenant quarantine endpoint; the pending
// surfaces must issue NO call at all (they short-circuit before the fixture getter).
describe('Fix A+B: real-mode HTTP behavior (fetch spy)', () => {
  function realModeWithToken(): ReturnType<typeof vi.fn> {
    vi.stubEnv('VITE_DIS_UI_SERVER_MODE', 'real')
    writeToken('stub.session.token') // client.ts sessionToken() requires a stored token
    const fetchSpy = vi.fn(async () => new Response('{"items":[],"open_count":0}', { status: 200 }))
    vi.stubGlobal('fetch', fetchSpy)
    return fetchSpy
  }

  it('TENANT DataQuality issues the real GET /api/v1/quarantine (tenant-scoped, not fleet)', async () => {
    const fetchSpy = realModeWithToken()
    render(<Wrap snapshot={TENANT}><DataQuality /></Wrap>)
    await screen.findByText('Rows that failed validation for your tenant.')
    await vi.waitFor(() => expect(fetchSpy).toHaveBeenCalled())
    const url = String(fetchSpy.mock.calls[0][0])
    expect(url).toContain('/api/v1/quarantine')
  })

  it('PLATFORM DataQuality issues the real GET /api/v1/quarantine (see-all, no more short-circuit)', async () => {
    const fetchSpy = realModeWithToken()
    render(<Wrap snapshot={PLATFORM}><DataQuality /></Wrap>)
    await vi.waitFor(() => expect(fetchSpy).toHaveBeenCalled())
    expect(String(fetchSpy.mock.calls[0][0])).toContain('/api/v1/quarantine')
  })

  it('Needs attention issues real fetches (derived feed, no longer short-circuited)', async () => {
    const fetchSpy = realModeWithToken()
    render(<Wrap snapshot={TENANT}><NotificationsRoute /></Wrap>)
    await vi.waitFor(() => expect(fetchSpy).toHaveBeenCalled())
  })

  it('SchemaDrift pending issues NO fetch', () => {
    const fetchSpy = realModeWithToken()
    render(<Wrap snapshot={TENANT}><SchemaDrift /></Wrap>)
    expect(screen.getByText('Schema Drift is a premium feature')).toBeInTheDocument()
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})
