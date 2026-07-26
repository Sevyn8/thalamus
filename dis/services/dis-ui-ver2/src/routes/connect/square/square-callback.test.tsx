import { screen } from '@testing-library/react'
import { Route, Routes, useSearchParams } from 'react-router'
import { vi } from 'vitest'

import { DisUiServerHttpError } from '../../../lib/dis-ui-server/client'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { SquareCallback } from './SquareCallback'

vi.mock('../../../lib/dis-ui-server/square-oauth', () => ({
  completeSquareOAuth: vi.fn(),
}))

import { completeSquareOAuth } from '../../../lib/dis-ui-server/square-oauth'

const SNAP = { userId: 'u', tenantId: 't', storeId: null, roles: [], userType: 'TENANT' as const }
const PLATFORM_SNAP = {
  userId: 'ops',
  tenantId: null,
  storeId: null,
  roles: ['dis:ops'],
  userType: 'PLATFORM' as const,
}

// A marker for the journey route so success navigation is observable (renders the query).
function JourneyMarker(): React.ReactElement {
  const [params] = useSearchParams()
  return <div>JOURNEY connected={params.get('connected')} source={params.get('source_id')}</div>
}

function renderCallback(entry: string, snapshot: typeof SNAP | typeof PLATFORM_SNAP = SNAP): void {
  renderWithProviders(
    <Routes>
      <Route path="/connectors/square/callback" element={<SquareCallback />} />
      <Route path="/connect/square" element={<JourneyMarker />} />
    </Routes>,
    { snapshot, initialEntries: [entry] },
  )
}

describe('SquareCallback', () => {
  beforeEach(() => vi.clearAllMocks())

  it('completes the exchange and routes into the journey (TENANT)', async () => {
    vi.mocked(completeSquareOAuth).mockResolvedValue({
      connector: 'square',
      status: 'connected',
      source_id: 'square_pos_v2',
      merchant_id: 'M1',
    })
    renderCallback('/connectors/square/callback?code=c&state=s')
    expect(await screen.findByText(/JOURNEY connected=1 source=square_pos_v2/)).toBeInTheDocument()
    expect(completeSquareOAuth).toHaveBeenCalledWith({ code: 'c', state: 's' })
  })

  it('completes the exchange for a PLATFORM caller too (tenant rides the state, not the body)', async () => {
    vi.mocked(completeSquareOAuth).mockResolvedValue({
      connector: 'square',
      status: 'connected',
      source_id: 'square_pos_v2',
      merchant_id: 'M2',
    })
    renderCallback('/connectors/square/callback?code=c&state=s', PLATFORM_SNAP)
    expect(await screen.findByText(/JOURNEY connected=1 source=square_pos_v2/)).toBeInTheDocument()
    // The client POSTs only {code, state}; the acted-for tenant was bound into the state.
    expect(completeSquareOAuth).toHaveBeenCalledWith({ code: 'c', state: 's' })
  })

  it('renders the typed failure and offers a retry back to the journey', async () => {
    vi.mocked(completeSquareOAuth).mockRejectedValue(
      new DisUiServerHttpError(502, 'square_token_exchange', 'boom', {}),
    )
    renderCallback('/connectors/square/callback?code=bad&state=s')
    expect(await screen.findByText(/Square could not complete the connection/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Back to Square setup/ })).toBeInTheDocument()
  })

  it('shows a declined message when the seller declines at Square (no exchange)', async () => {
    renderCallback('/connectors/square/callback?error=access_denied')
    expect(await screen.findByText(/Square authorization was declined/)).toBeInTheDocument()
    expect(completeSquareOAuth).not.toHaveBeenCalled()
  })

  it('shows a missing-code message when code/state are absent', async () => {
    renderCallback('/connectors/square/callback')
    expect(await screen.findByText(/missing its authorization code/)).toBeInTheDocument()
    expect(completeSquareOAuth).not.toHaveBeenCalled()
  })
})
