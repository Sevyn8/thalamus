import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { Auth0AuthProvider } from './Auth0AuthProvider'
import { useAuth } from './useAuth'

// The snapshot + token-ready pair the provider exposes is DERIVED from the fetched
// token during render, not synced back through an effect. These pin the two
// properties that derivation has to preserve: a fetched token surfaces as
// 'authenticated' with its claims, and Auth0 reporting no session surfaces as no
// snapshot — including after a session that had already produced one.

vi.mock('@auth0/auth0-react', () => ({ useAuth0: vi.fn() }))
vi.mock('./storage', () => ({ writeToken: vi.fn(), clearToken: vi.fn() }))

import { useAuth0 } from '@auth0/auth0-react'

import { clearToken, writeToken } from './storage'

// A dev-stub-shaped token: header.payload.signature, payload carrying the namespaced
// custom claims the provider decodes (advisory decode only; no signature check).
function tokenFor(sub: string, tenantId: string | null): string {
  const payload = {
    sub,
    'https://sevyn8.com/tenant_id': tenantId,
    'https://sevyn8.com/user_type': 'TENANT',
    'https://sevyn8.com/roles': ['dis:read'],
  }
  const b64 = (o: unknown) =>
    btoa(JSON.stringify(o)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
  return `${b64({ alg: 'HS256', typ: 'JWT' })}.${b64(payload)}.sig`
}

function Probe() {
  const { status, snapshot } = useAuth()
  return (
    <div>
      <span data-testid="status">{status}</span>
      <span data-testid="tenant">{snapshot === null ? 'NO_SNAPSHOT' : snapshot.tenantId}</span>
    </div>
  )
}

function mockAuth0(overrides: Record<string, unknown>) {
  vi.mocked(useAuth0).mockReturnValue({
    isLoading: false,
    isAuthenticated: false,
    user: undefined,
    getAccessTokenSilently: vi.fn(),
    loginWithRedirect: vi.fn().mockResolvedValue(undefined),
    logout: vi.fn(),
    error: undefined,
    ...overrides,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- the SDK's return type is far wider than this provider reads
  } as any)
}

describe('Auth0AuthProvider', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('surfaces a fetched token as authenticated, with the decoded claims', async () => {
    mockAuth0({
      isAuthenticated: true,
      user: { sub: 'auth0|u1' },
      getAccessTokenSilently: vi.fn().mockResolvedValue(tokenFor('auth0|u1', 'tenant-a')),
    })
    render(
      <Auth0AuthProvider>
        <Probe />
      </Auth0AuthProvider>,
    )
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'))
    expect(screen.getByTestId('tenant')).toHaveTextContent('tenant-a')
    expect(writeToken).toHaveBeenCalledOnce()
  })

  it('holds at loading while the token fetch is still in flight', async () => {
    mockAuth0({
      isAuthenticated: true,
      user: { sub: 'auth0|u1' },
      // Never resolves: the bearer is not in storage yet, so consumers must not be
      // told they are authenticated.
      getAccessTokenSilently: vi.fn().mockReturnValue(new Promise(() => {})),
    })
    render(
      <Auth0AuthProvider>
        <Probe />
      </Auth0AuthProvider>,
    )
    expect(screen.getByTestId('status')).toHaveTextContent('loading')
    expect(screen.getByTestId('tenant')).toHaveTextContent('NO_SNAPSHOT')
  })

  it('exposes no snapshot once Auth0 reports no session', async () => {
    mockAuth0({ isAuthenticated: false })
    render(
      <Auth0AuthProvider>
        <Probe />
      </Auth0AuthProvider>,
    )
    expect(screen.getByTestId('tenant')).toHaveTextContent('NO_SNAPSHOT')
    expect(screen.getByTestId('status')).not.toHaveTextContent('authenticated')
  })

  it('drops the snapshot when a previously authenticated session ends', async () => {
    mockAuth0({
      isAuthenticated: true,
      user: { sub: 'auth0|u1' },
      getAccessTokenSilently: vi.fn().mockResolvedValue(tokenFor('auth0|u1', 'tenant-a')),
    })
    const view = render(
      <Auth0AuthProvider>
        <Probe />
      </Auth0AuthProvider>,
    )
    await waitFor(() => expect(screen.getByTestId('tenant')).toHaveTextContent('tenant-a'))

    // The session goes away without the component unmounting. The stored fetch result
    // must become unreachable — this is the case the removed reset-effect covered.
    mockAuth0({ isAuthenticated: false })
    view.rerender(
      <Auth0AuthProvider>
        <Probe />
      </Auth0AuthProvider>,
    )
    expect(screen.getByTestId('tenant')).toHaveTextContent('NO_SNAPSHOT')
    expect(screen.getByTestId('status')).not.toHaveTextContent('authenticated')
  })

  it('clears the token and exposes no snapshot when the fetch fails', async () => {
    mockAuth0({
      isAuthenticated: true,
      user: { sub: 'auth0|u1' },
      getAccessTokenSilently: vi.fn().mockRejectedValue(new Error('login_required')),
    })
    render(
      <Auth0AuthProvider>
        <Probe />
      </Auth0AuthProvider>,
    )
    await waitFor(() => expect(clearToken).toHaveBeenCalledOnce())
    expect(screen.getByTestId('tenant')).toHaveTextContent('NO_SNAPSHOT')
    expect(screen.getByTestId('status')).toHaveTextContent('loading')
  })
})
