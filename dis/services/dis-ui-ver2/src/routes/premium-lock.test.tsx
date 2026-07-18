import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { AuthSnapshot } from '../auth/AuthSnapshot'
import { AuthContext } from '../auth/context'
import type { AuthContextValue } from '../auth/context'
import { PremiumLock } from '../components/PremiumLock'
import { Credentials } from './Credentials'
import { SchemaDrift } from './SchemaDrift'

const TENANT: AuthSnapshot = {
  userId: 'u',
  tenantId: 't_acme9k2l1mn4',
  storeId: 's',
  userType: 'TENANT',
  roles: ['dis:read'],
}

function Wrap({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const authValue: AuthContextValue = {
    status: 'authenticated',
    snapshot: TENANT,
    login: () => Promise.resolve(),
    logout: () => {},
  }
  return (
    <QueryClientProvider client={qc}>
      <AuthContext.Provider value={authValue}>
        <MemoryRouter>{children}</MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>
  )
}

describe('PremiumLock variants', () => {
  it('variant="fade" (A) renders the lock banner AND its children beneath it', () => {
    const { container } = render(
      <Wrap>
        <PremiumLock title="Test Feature is a premium feature" variant="fade">
          <div>real child content</div>
        </PremiumLock>
      </Wrap>,
    )
    expect(screen.getByText('Test Feature is a premium feature')).toBeInTheDocument()
    expect(screen.getByText(/available on a higher plan/)).toBeInTheDocument()
    const content = container.querySelector('.premium-lock__content')
    expect(content?.textContent).toContain('real child content')
  })

  it('variant="replace" (B) renders ONLY the lock message — no content region, no children', () => {
    const { container } = render(
      <Wrap>
        <PremiumLock title="Test Feature is a premium feature" variant="replace">
          <div>real child content</div>
        </PremiumLock>
      </Wrap>,
    )
    expect(screen.getByText('Test Feature is a premium feature')).toBeInTheDocument()
    // No faded content region, and the children are NOT rendered.
    expect(container.querySelector('.premium-lock__content')).toBeNull()
    expect(screen.queryByText('real child content')).not.toBeInTheDocument()
  })
})

// Treatment B: Schema Drift + Credentials render ONLY the H1 + the lock message. No subtitle, no
// empty-state/body, no faded content region, and NO backend fetch (they mount no data hooks).
describe('Schema Drift (Treatment B)', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllEnvs()
    localStorage.clear()
  })

  it('renders H1 + lock message only — no subtitle, no body', () => {
    const { container } = render(
      <Wrap>
        <SchemaDrift />
      </Wrap>,
    )
    expect(screen.getByRole('heading', { name: 'Schema Drift & Changes' })).toBeInTheDocument()
    expect(screen.getByText('Schema Drift is a premium feature')).toBeInTheDocument()
    // Removed strings are GONE from the render path.
    expect(
      screen.queryByText(/Shadow comparison of a staged mapping/),
    ).not.toBeInTheDocument()
    expect(screen.queryByText('Nothing staged to compare')).not.toBeInTheDocument()
    expect(screen.queryByText('No shadow run')).not.toBeInTheDocument()
    expect(screen.queryByText(/No staged version to compare/)).not.toBeInTheDocument()
    expect(container.querySelector('.premium-lock__content')).toBeNull()
  })

  it('fires NO backend fetch (even in real mode)', () => {
    vi.stubEnv('VITE_DIS_UI_SERVER_MODE', 'real')
    localStorage.setItem('dis-ui.dev.authToken', 'stub')
    const fetchSpy = vi.fn(async () => new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetchSpy)
    render(
      <Wrap>
        <SchemaDrift />
      </Wrap>,
    )
    expect(screen.getByText('Schema Drift is a premium feature')).toBeInTheDocument()
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})

describe('Credentials (Treatment B)', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllEnvs()
    localStorage.clear()
  })

  it('renders H1 + lock message only — no subtitle, note, or empty state, and never a secret', () => {
    const { container } = render(
      <Wrap>
        <Credentials />
      </Wrap>,
    )
    expect(screen.getByRole('heading', { name: 'Credentials & Secrets' })).toBeInTheDocument()
    expect(screen.getByText('Credentials & Secrets is a premium feature')).toBeInTheDocument()
    // Removed strings are GONE from the render path.
    expect(
      screen.queryByText(/Integration credentials, secrets, and keys/),
    ).not.toBeInTheDocument()
    expect(screen.queryByText('No credentials yet')).not.toBeInTheDocument()
    expect(screen.queryByText(/Credentials for your connected sources/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Secrets are stored securely/)).not.toBeInTheDocument()
    expect(container.querySelector('.premium-lock__content')).toBeNull()
  })

  it('fires NO backend fetch (even in real mode)', () => {
    vi.stubEnv('VITE_DIS_UI_SERVER_MODE', 'real')
    localStorage.setItem('dis-ui.dev.authToken', 'stub')
    const fetchSpy = vi.fn(async () => new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetchSpy)
    render(
      <Wrap>
        <Credentials />
      </Wrap>,
    )
    expect(screen.getByText('Credentials & Secrets is a premium feature')).toBeInTheDocument()
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})
