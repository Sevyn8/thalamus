import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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
      <span data-testid="user">{snapshot === null ? 'NO_SNAPSHOT' : snapshot.userId}</span>
      <span data-testid="roles">{snapshot === null ? 'NO_SNAPSHOT' : snapshot.roles.join(',')}</span>
    </div>
  )
}

// A promise whose resolution this test controls, so "the new session's token has
// not arrived yet" is an observable state rather than a race.
function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((r) => {
    resolve = r
  })
  return { promise, resolve }
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

// ---------------------------------------------------------------------------
// Re-authentication: no state from a finished session may survive into the next
// one. The derivation that replaced the reset-effect keeps the fetched snapshot
// in state across an unauthenticated interval, so these pin the property that
// makes that safe: a snapshot is only ever visible to the session that fetched it.
// ---------------------------------------------------------------------------
describe('Auth0AuthProvider re-authentication', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // CASE 1: a different tenant/user signs in while the new token is still in flight.
  it('never shows the previous user while the next session is still fetching', async () => {
    mockAuth0({
      isAuthenticated: true,
      user: { sub: 'auth0|userA' },
      getAccessTokenSilently: vi.fn().mockResolvedValue(tokenFor('auth0|userA', 'tenant-a')),
    })
    const view = render(
      <Auth0AuthProvider>
        <Probe />
      </Auth0AuthProvider>,
    )
    await waitFor(() => expect(screen.getByTestId('tenant')).toHaveTextContent('tenant-a'))

    // Session ends.
    mockAuth0({ isAuthenticated: false })
    view.rerender(
      <Auth0AuthProvider>
        <Probe />
      </Auth0AuthProvider>,
    )
    expect(screen.getByTestId('tenant')).toHaveTextContent('NO_SNAPSHOT')

    // A DIFFERENT user signs in; their token has not resolved yet.
    const pending = deferred<string>()
    mockAuth0({
      isAuthenticated: true,
      user: { sub: 'auth0|userB' },
      getAccessTokenSilently: vi.fn().mockReturnValue(pending.promise),
    })
    view.rerender(
      <Auth0AuthProvider>
        <Probe />
      </Auth0AuthProvider>,
    )

    // A's identity must not be observable, and B must not be called authenticated
    // before B's bearer exists.
    expect(screen.getByTestId('status')).not.toHaveTextContent('authenticated')
    expect(screen.getByTestId('tenant')).toHaveTextContent('NO_SNAPSHOT')
    expect(screen.getByTestId('user')).toHaveTextContent('NO_SNAPSHOT')
    expect(screen.getByTestId('roles')).toHaveTextContent('NO_SNAPSHOT')

    // Only once B's token lands does B become authenticated.
    pending.resolve(tokenFor('auth0|userB', 'tenant-b'))
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'))
    expect(screen.getByTestId('tenant')).toHaveTextContent('tenant-b')
    expect(screen.getByTestId('user')).toHaveTextContent('auth0|userB')
  })

  // CASE 2: explicit logout, then sign in again while the new token is in flight.
  it('does not resurrect the logged-out snapshot on re-login', async () => {
    const logout = vi.fn()
    mockAuth0({
      isAuthenticated: true,
      user: { sub: 'auth0|userA' },
      getAccessTokenSilently: vi.fn().mockResolvedValue(tokenFor('auth0|userA', 'tenant-a')),
      logout,
    })
    function LogoutProbe() {
      const auth = useAuth()
      return (
        <button type="button" onClick={() => auth.logout()}>
          sign out
        </button>
      )
    }
    const view = render(
      <Auth0AuthProvider>
        <Probe />
        <LogoutProbe />
      </Auth0AuthProvider>,
    )
    await waitFor(() => expect(screen.getByTestId('tenant')).toHaveTextContent('tenant-a'))

    // The provider's logout clears the local bearer and asks the SDK to end the session.
    await userEvent.click(screen.getByRole('button', { name: 'sign out' }))
    expect(clearToken).toHaveBeenCalled()
    expect(logout).toHaveBeenCalled()

    mockAuth0({ isAuthenticated: false })
    view.rerender(
      <Auth0AuthProvider>
        <Probe />
        <LogoutProbe />
      </Auth0AuthProvider>,
    )
    expect(screen.getByTestId('tenant')).toHaveTextContent('NO_SNAPSHOT')

    // Signing back in; the replacement token has not arrived.
    const pending = deferred<string>()
    mockAuth0({
      isAuthenticated: true,
      user: { sub: 'auth0|userA' },
      getAccessTokenSilently: vi.fn().mockReturnValue(pending.promise),
    })
    view.rerender(
      <Auth0AuthProvider>
        <Probe />
        <LogoutProbe />
      </Auth0AuthProvider>,
    )

    expect(screen.getByTestId('status')).toHaveTextContent('loading')
    expect(screen.getByTestId('tenant')).toHaveTextContent('NO_SNAPSHOT')
  })

  // CASE 3: the SAME Auth0 subject signs in again. A fix that compares user.sub
  // cannot tell this apart from "still the same session", so it would let the
  // stale access-token snapshot through here.
  it('drops the snapshot even when the same subject re-authenticates', async () => {
    mockAuth0({
      isAuthenticated: true,
      user: { sub: 'auth0|same' },
      getAccessTokenSilently: vi.fn().mockResolvedValue(tokenFor('auth0|same', 'tenant-first')),
    })
    const view = render(
      <Auth0AuthProvider>
        <Probe />
      </Auth0AuthProvider>,
    )
    await waitFor(() => expect(screen.getByTestId('tenant')).toHaveTextContent('tenant-first'))

    mockAuth0({ isAuthenticated: false })
    view.rerender(
      <Auth0AuthProvider>
        <Probe />
      </Auth0AuthProvider>,
    )

    const pending = deferred<string>()
    mockAuth0({
      isAuthenticated: true,
      user: { sub: 'auth0|same' },
      getAccessTokenSilently: vi.fn().mockReturnValue(pending.promise),
    })
    view.rerender(
      <Auth0AuthProvider>
        <Probe />
      </Auth0AuthProvider>,
    )

    // Same subject, but a NEW session whose bearer is not ready.
    expect(screen.getByTestId('status')).not.toHaveTextContent('authenticated')
    expect(screen.getByTestId('tenant')).toHaveTextContent('NO_SNAPSHOT')

    pending.resolve(tokenFor('auth0|same', 'tenant-second'))
    await waitFor(() => expect(screen.getByTestId('tenant')).toHaveTextContent('tenant-second'))
  })
})
