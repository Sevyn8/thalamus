import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import { vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'
import { SquareJourney } from './SquareJourney'

// Mock the three real write/connect seams; the journey test asserts the calls + step transitions,
// not the backend behavior (covered by their own tests).
vi.mock('../../../lib/dis-ui-server/sources', () => ({
  createSourceIfAbsent: vi.fn().mockResolvedValue(true),
}))
vi.mock('../../../lib/dis-ui-server/mapping-templates', () => ({
  createMappingTemplate: vi.fn().mockResolvedValue({ template_id: 'tmpl_1' }),
}))
vi.mock('../../../lib/dis-ui-server/square-oauth', () => ({
  getSquareAuthorizeUrl: vi.fn().mockResolvedValue({ authorize_url: 'https://sq.test/x', state: 's' }),
}))

import { createMappingTemplate } from '../../../lib/dis-ui-server/mapping-templates'
import { createSourceIfAbsent } from '../../../lib/dis-ui-server/sources'
import { getSquareAuthorizeUrl } from '../../../lib/dis-ui-server/square-oauth'

const SNAP = { userId: 'u', tenantId: 't', storeId: null, roles: [], userType: 'TENANT' as const }

function renderJourney(entry: string): void {
  renderWithProviders(
    <Routes>
      <Route path="/connect/square" element={<SquareJourney />} />
      <Route path="/connect" element={<div>SOURCES GRID</div>} />
    </Routes>,
    { snapshot: SNAP, initialEntries: [entry] },
  )
}

describe('SquareJourney', () => {
  beforeEach(() => vi.clearAllMocks())

  it('registers the source + template, then advances to the Connect step', async () => {
    renderJourney('/connect/square')
    fireEvent.click(screen.getByRole('button', { name: /Register source & template/ }))
    await screen.findByRole('button', { name: /Sign in with Square/ })
    expect(createSourceIfAbsent).toHaveBeenCalledWith(
      expect.objectContaining({ source_id: 'square_pos_v2', channel: 'api', store_id: 'W-001' }),
    )
    expect(createMappingTemplate).toHaveBeenCalledWith(
      expect.objectContaining({ source_id: 'square_pos_v2', template_type: 'snapshot' }),
    )
  })

  it('requests the authorize URL for the Square source on Connect', async () => {
    renderJourney('/connect/square')
    fireEvent.click(screen.getByRole('button', { name: /Register source & template/ }))
    fireEvent.click(await screen.findByRole('button', { name: /Sign in with Square/ }))
    await waitFor(() => expect(getSquareAuthorizeUrl).toHaveBeenCalledWith('square_pos_v2'))
  })

  it('shows the first-pull affordance with run/canonical links when returning connected', () => {
    renderJourney('/connect/square?connected=1&source_id=square_pos_v2&merchant_id=M1')
    expect(screen.getByText(/Square is connected/)).toBeInTheDocument()
    expect(screen.getByText('M1')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /View Ingestion Runs/ })).toHaveAttribute(
      'href',
      '/ingestion-runs',
    )
    expect(screen.getByRole('link', { name: /Open Canonical Explorer/ })).toHaveAttribute(
      'href',
      '/canonical',
    )
  })
})
