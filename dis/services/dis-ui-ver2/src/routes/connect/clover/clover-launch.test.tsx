import { screen, waitFor } from '@testing-library/react'
import { Route, Routes, useLocation } from 'react-router'
import { vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'
import { CloverCallback } from './CloverCallback'
import { CloverLaunch } from './CloverLaunch'

vi.mock('../../../lib/dis-ui-server/clover-oauth', () => ({
  completeCloverOAuth: vi.fn().mockResolvedValue({
    connector: 'clover',
    status: 'connected',
    source_id: 'clover_pos_v1',
    merchant_id: '0RKKDBMKPAH71',
  }),
}))

import { completeCloverOAuth } from '../../../lib/dis-ui-server/clover-oauth'
import { DisUiServerHttpError } from '../../../lib/dis-ui-server/client'

const TENANT = { userId: 'u', tenantId: 't', storeId: null, roles: [], userType: 'TENANT' as const }

// Destination stubs print the resolved URL so a test can assert WHERE the branch landed.
function render(entry: string): void {
  renderWithProviders(
    <Routes>
      <Route path="/connectors/clover/launch" element={<CloverLaunch />} />
      <Route path="/connectors/clover/callback" element={<CloverCallback />} />
      <Route path="/connect/clover" element={<Landed label="JOURNEY" />} />
      <Route path="/connect" element={<Landed label="CATALOGUE" />} />
    </Routes>,
    { snapshot: TENANT, initialEntries: [entry] },
  )
}

function Landed({ label }: { label: string }) {
  // MemoryRouter never touches window.location, so read the resolved query off the router.
  const { search } = useLocation()
  return <div>{`${label}${search}`}</div>
}

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
})

// -- the three inbound shapes (D4) ---------------------------------------------------------

test('branch 1: merchant_id + code exchanges and lands on the first-pull step', async () => {
  render('/connectors/clover/launch?merchant_id=0RKKDBMKPAH71&code=abc&state=xyz')
  await waitFor(() => expect(completeCloverOAuth).toHaveBeenCalled())
  expect(completeCloverOAuth).toHaveBeenCalledWith({
    code: 'abc',
    state: 'xyz',
    merchant_id: '0RKKDBMKPAH71',
  })
  const landed = await screen.findByText(/^JOURNEY/)
  expect(landed.textContent).toContain('connected=1')
  expect(landed.textContent).toContain('merchant_id=0RKKDBMKPAH71')
})

test('branch 2: merchant_id with NO code resumes at connect, naming the merchant', async () => {
  // Installed from the App Market but not yet authorised - Clover launches the app with a
  // merchant and no code. Nothing is exchanged.
  render('/connectors/clover/launch?merchant_id=0RKKDBMKPAH71')
  const landed = await screen.findByText(/^JOURNEY/)
  expect(landed.textContent).toContain('step=connect')
  expect(landed.textContent).toContain('merchant_id=0RKKDBMKPAH71')
  expect(completeCloverOAuth).not.toHaveBeenCalled()
})

test('branch 3: neither parameter sends a context-free arrival to the catalogue', async () => {
  render('/connectors/clover/launch')
  await screen.findByText(/^CATALOGUE/)
  expect(completeCloverOAuth).not.toHaveBeenCalled()
})

test('a code with no state is treated as not-yet-authorised, not exchanged', async () => {
  // A half-formed callback must never reach the exchange with an empty state.
  render('/connectors/clover/launch?merchant_id=M1&code=abc')
  await screen.findByText(/^JOURNEY/)
  expect(completeCloverOAuth).not.toHaveBeenCalled()
})

// -- the single-use code -------------------------------------------------------------------

test('the exchange fires once even though the effect may run twice', async () => {
  render('/connectors/clover/launch?merchant_id=M1&code=abc&state=xyz')
  await waitFor(() => expect(completeCloverOAuth).toHaveBeenCalled())
  expect(completeCloverOAuth).toHaveBeenCalledTimes(1)
})

test('the callback FORWARDS to launch and does not exchange itself', async () => {
  // One state machine, one place able to spend the single-use code.
  render('/connectors/clover/callback?merchant_id=M1&code=abc&state=xyz')
  await waitFor(() => expect(completeCloverOAuth).toHaveBeenCalledTimes(1))
  await screen.findByText(/^JOURNEY/)
})

// -- error copy (D8) --------------------------------------------------------------------------

test.each([
  ['invalid_oauth_state', /link has expired/i],
  ['oauth_state_tenant_mismatch', /different account/i],
  ['clover_token_exchange', /did not complete/i],
  ['oauth_not_configured', /not available on this environment/i],
])('%s renders client-facing copy carrying no error code', async (code, expected) => {
  vi.mocked(completeCloverOAuth).mockRejectedValueOnce(
    new DisUiServerHttpError(422, code, 'raw vendor text', {}),
  )
  render('/connectors/clover/launch?merchant_id=M1&code=abc&state=xyz')
  const alert = await screen.findByRole('alert')
  expect(alert.textContent).toMatch(expected)
  expect(alert.textContent).not.toContain(code)
  expect(alert.textContent).not.toContain('raw vendor text')
})
