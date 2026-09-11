import { act, render, screen, waitFor } from '@testing-library/react'
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

// A real (in-memory) bearer store rather than bare spies. The stale-token races
// below are about what is left SITTING IN STORAGE after an out-of-order write, which
// call counts alone cannot show: a late writeToken() following a clearToken() is two
// ordinary-looking calls and one restored credential.
const storage = vi.hoisted(() => {
  let token: string | null = null
  return {
    writeToken: vi.fn((value: string) => {
      token = value
    }),
    clearToken: vi.fn(() => {
      token = null
    }),
    read: () => token,
    reset: () => {
      token = null
    },
  }
})
vi.mock('./storage', () => ({ writeToken: storage.writeToken, clearToken: storage.clearToken }))

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
function deferred<T>(): {
  promise: Promise<T>
  resolve: (value: T) => void
  reject: (reason: unknown) => void
} {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  // An unobserved rejection is a test-runner failure, not a provider failure: the
  // point of these cases is that the PROVIDER ignores the rejection, so keep a
  // no-op observer attached.
  promise.catch(() => {})
  return { promise, resolve, reject }
}

// Flush pending microtasks and the React work they schedule, deterministically —
// no timers, no polling. Every assertion below about something NOT happening runs
// after one of these.
async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
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
    storage.reset()
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
    storage.reset()
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

// ---------------------------------------------------------------------------
// STALE TOKEN FETCHES. Session boundaries are not the only way a previous
// session's work can land late. An in-flight getAccessTokenSilently() outlives
// the decision to log out, and the Auth0 SDK does not report isAuthenticated=false
// synchronously — so between "logout starts" and "Auth0 catches up" there is a
// window where an effect-local guard has not been torn down and the old promise
// can still write. These pin that no async result created before logout, success
// or failure, may ever touch bearer storage or session state again.
// ---------------------------------------------------------------------------
const TOKEN_A = () => tokenFor('auth0|userA', 'tenant-A')
const TOKEN_B = () => tokenFor('auth0|userB', 'tenant-B')

function LogoutButton() {
  const auth = useAuth()
  return (
    <button type="button" onClick={() => auth.logout()}>
      sign out
    </button>
  )
}

function renderProvider() {
  return render(
    <Auth0AuthProvider>
      <Probe />
      <LogoutButton />
    </Auth0AuthProvider>,
  )
}

function rerenderProvider(view: ReturnType<typeof renderProvider>) {
  view.rerender(
    <Auth0AuthProvider>
      <Probe />
      <LogoutButton />
    </Auth0AuthProvider>,
  )
}

describe('Auth0AuthProvider stale token fetches', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    storage.reset()
  })

  // TEST 1 — the window the effect-local `active` flag cannot cover: logout has
  // begun, but Auth0 still reports authenticated, so no dependency changed and no
  // cleanup ran. The pending request must already be dead.
  it('ignores a token that resolves after logout but before Auth0 reports no session', async () => {
    const pendingA = deferred<string>()
    mockAuth0({
      isAuthenticated: true,
      user: { sub: 'auth0|userA' },
      getAccessTokenSilently: vi.fn().mockReturnValue(pendingA.promise),
    })
    renderProvider()

    await userEvent.click(screen.getByRole('button', { name: 'sign out' }))
    // Logout cleared the bearer straight away...
    expect(storage.read()).toBeNull()

    // ...and Auth0 has NOT yet flipped isAuthenticated. The old request resolves now.
    pendingA.resolve(TOKEN_A())
    await flush()

    expect(storage.read()).toBeNull() // the credential must NOT come back
    expect(writeToken).not.toHaveBeenCalled()
    expect(screen.getByTestId('status')).not.toHaveTextContent('authenticated')
    expect(screen.getByTestId('tenant')).toHaveTextContent('NO_SNAPSHOT')
    expect(screen.getByTestId('user')).toHaveTextContent('NO_SNAPSHOT')
    expect(screen.getByTestId('roles')).toHaveTextContent('NO_SNAPSHOT')
  })

  // TEST 2 — same subject on both sides of the gap, old success landing first.
  it('ignores a stale success when the SAME subject has signed back in', async () => {
    const pendingA1 = deferred<string>()
    mockAuth0({
      isAuthenticated: true,
      user: { sub: 'auth0|userA' },
      getAccessTokenSilently: vi.fn().mockReturnValue(pendingA1.promise),
    })
    const view = renderProvider()

    await userEvent.click(screen.getByRole('button', { name: 'sign out' }))
    mockAuth0({ isAuthenticated: false })
    rerenderProvider(view)

    const pendingA2 = deferred<string>()
    mockAuth0({
      isAuthenticated: true,
      user: { sub: 'auth0|userA' }, // identical subject
      getAccessTokenSilently: vi.fn().mockReturnValue(pendingA2.promise),
    })
    rerenderProvider(view)

    // The OLD request resolves first.
    pendingA1.resolve(TOKEN_A())
    await flush()
    expect(storage.read()).toBeNull()
    expect(screen.getByTestId('status')).not.toHaveTextContent('authenticated')
    expect(screen.getByTestId('tenant')).toHaveTextContent('NO_SNAPSHOT')

    // Only the new request may establish the session.
    pendingA2.resolve(tokenFor('auth0|userA', 'tenant-second'))
    await flush()
    expect(storage.read()).toBe(tokenFor('auth0|userA', 'tenant-second'))
    expect(screen.getByTestId('tenant')).toHaveTextContent('tenant-second')
    expect(screen.getByTestId('status')).toHaveTextContent('authenticated')
  })

  // TEST 3 — different subject, old success landing after the new request began.
  it('ignores a stale success from a different user after re-login', async () => {
    const pendingA = deferred<string>()
    mockAuth0({
      isAuthenticated: true,
      user: { sub: 'auth0|userA' },
      getAccessTokenSilently: vi.fn().mockReturnValue(pendingA.promise),
    })
    const view = renderProvider()

    await userEvent.click(screen.getByRole('button', { name: 'sign out' }))
    mockAuth0({ isAuthenticated: false })
    rerenderProvider(view)

    const pendingB = deferred<string>()
    mockAuth0({
      isAuthenticated: true,
      user: { sub: 'auth0|userB' },
      getAccessTokenSilently: vi.fn().mockReturnValue(pendingB.promise),
    })
    rerenderProvider(view)

    pendingA.resolve(TOKEN_A())
    await flush()
    expect(storage.read()).toBeNull()
    expect(screen.getByTestId('tenant')).not.toHaveTextContent('tenant-A')
    expect(screen.getByTestId('user')).not.toHaveTextContent('auth0|userA')
    expect(screen.getByTestId('status')).not.toHaveTextContent('authenticated')

    pendingB.resolve(TOKEN_B())
    await flush()
    expect(storage.read()).toBe(TOKEN_B())
    expect(screen.getByTestId('tenant')).toHaveTextContent('tenant-B')
    expect(screen.getByTestId('status')).toHaveTextContent('authenticated')
  })

  // TEST 4 — the dangerous direction: a stale FAILURE arriving after the new
  // session already succeeded. Its error path clears storage and the snapshot, so
  // an unguarded rejection logs the new user out.
  it('lets a stale rejection do nothing to an already-established new session', async () => {
    const pendingA = deferred<string>()
    mockAuth0({
      isAuthenticated: true,
      user: { sub: 'auth0|userA' },
      getAccessTokenSilently: vi.fn().mockReturnValue(pendingA.promise),
    })
    const view = renderProvider()

    await userEvent.click(screen.getByRole('button', { name: 'sign out' }))
    mockAuth0({ isAuthenticated: false })
    rerenderProvider(view)

    // Same subject: the harder case for anything comparing identity.
    const pendingB = deferred<string>()
    mockAuth0({
      isAuthenticated: true,
      user: { sub: 'auth0|userA' },
      getAccessTokenSilently: vi.fn().mockReturnValue(pendingB.promise),
    })
    rerenderProvider(view)

    pendingB.resolve(TOKEN_B())
    await flush()
    expect(storage.read()).toBe(TOKEN_B())
    expect(screen.getByTestId('status')).toHaveTextContent('authenticated')

    // Now the abandoned request fails.
    pendingA.reject(new Error('login_required'))
    await flush()

    expect(storage.read()).toBe(TOKEN_B()) // still signed in
    expect(screen.getByTestId('tenant')).toHaveTextContent('tenant-B')
    expect(screen.getByTestId('status')).toHaveTextContent('authenticated')
  })

  // TEST 4b — the rejection half of TEST 1's window, and the only place the catch
  // path's epoch check is load-bearing: logout has begun, Auth0 has NOT yet reported
  // false, so no dependency changed and the effect-local `active` flag is still true.
  // An unguarded error path would run clearToken() and setSession() on behalf of a
  // session the user already abandoned — storage writes from a dead request.
  it('lets a rejection arriving in the logout window touch nothing', async () => {
    const pendingA = deferred<string>()
    mockAuth0({
      isAuthenticated: true,
      user: { sub: 'auth0|userA' },
      getAccessTokenSilently: vi.fn().mockReturnValue(pendingA.promise),
    })
    renderProvider()

    await userEvent.click(screen.getByRole('button', { name: 'sign out' }))
    expect(clearToken).toHaveBeenCalledTimes(1) // logout's own clear

    pendingA.reject(new Error('login_required'))
    await flush()

    // The abandoned request must not have reached storage at all — not even to
    // clear it again. Exactly one clear happened, and logout made it.
    expect(clearToken).toHaveBeenCalledTimes(1)
    expect(writeToken).not.toHaveBeenCalled()
    expect(storage.read()).toBeNull()
    expect(screen.getByTestId('status')).not.toHaveTextContent('authenticated')
  })

  // TEST 5 — defence in depth. A session can end without travelling through the
  // provider's logout callback at all (SDK-side expiry, another tab). When Auth0
  // says there is no session, the bearer must not still be sitting in storage.
  it('empties bearer storage when Auth0 reports no session, without an explicit logout', async () => {
    mockAuth0({
      isAuthenticated: true,
      user: { sub: 'auth0|userA' },
      getAccessTokenSilently: vi.fn().mockResolvedValue(TOKEN_A()),
    })
    const view = renderProvider()
    await waitFor(() => expect(storage.read()).toBe(TOKEN_A()))

    mockAuth0({ isAuthenticated: false })
    rerenderProvider(view)
    await flush()

    expect(storage.read()).toBeNull()
    expect(screen.getByTestId('tenant')).toHaveTextContent('NO_SNAPSHOT')
    expect(screen.getByTestId('status')).not.toHaveTextContent('authenticated')
  })
})
