import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import { vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'
import { SquareJourney } from './SquareJourney'

// Mock the write/connect seams + the sources read (the tenant picker). tenant-label stays real.
const FLEET_SOURCES = [
  { tenant_id: 'ten-acme', tenant_name: 'Acme Retail' },
  { tenant_id: 'ten-zabka', tenant_name: 'Zabka Group' },
]

vi.mock('../../../lib/dis-ui-server/sources', () => ({
  createSourceIfAbsent: vi.fn().mockResolvedValue(true),
  useSources: vi.fn(() => ({ data: FLEET_SOURCES, isPending: false })),
}))
vi.mock('../../../lib/dis-ui-server/mapping-templates', () => ({
  createMappingTemplateIfAbsent: vi.fn().mockResolvedValue(true),
}))
vi.mock('../../../lib/dis-ui-server/square-oauth', () => ({
  getSquareAuthorizeUrl: vi.fn().mockResolvedValue({ authorize_url: 'https://sq.test/x', state: 's' }),
}))

import { createMappingTemplateIfAbsent } from '../../../lib/dis-ui-server/mapping-templates'
import { createSourceIfAbsent } from '../../../lib/dis-ui-server/sources'
import { getSquareAuthorizeUrl } from '../../../lib/dis-ui-server/square-oauth'

const TENANT_SNAP = { userId: 'u', tenantId: 't', storeId: null, roles: [], userType: 'TENANT' as const }
const PLATFORM_SNAP = {
  userId: 'ops',
  tenantId: null,
  storeId: null,
  roles: ['dis:ops'],
  userType: 'PLATFORM' as const,
}

function renderJourney(entry: string, snapshot: typeof TENANT_SNAP | typeof PLATFORM_SNAP): void {
  renderWithProviders(
    <Routes>
      <Route path="/connect/square" element={<SquareJourney />} />
      <Route path="/connect" element={<div>SOURCES GRID</div>} />
    </Routes>,
    { snapshot, initialEntries: [entry] },
  )
}

describe('SquareJourney — TENANT persona', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sessionStorage.clear()
  })

  it('registers with NO acted-for tenant, then advances to Connect', async () => {
    renderJourney('/connect/square', TENANT_SNAP)
    // No tenant picker for a TENANT caller.
    expect(screen.queryByLabelText('Tenant to connect')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /Register source & template/ }))
    await screen.findByRole('button', { name: /Sign in with Square/ })
    expect(createSourceIfAbsent).toHaveBeenCalledWith(
      expect.objectContaining({ source_id: 'square_pos_v2', acting_for_tenant_id: undefined }),
    )
    expect(createMappingTemplateIfAbsent).toHaveBeenCalledWith(
      expect.objectContaining({ template_type: 'snapshot', acting_for_tenant_id: undefined }),
    )
  })

  it('requests the authorize URL with no acted-for tenant', async () => {
    renderJourney('/connect/square', TENANT_SNAP)
    fireEvent.click(screen.getByRole('button', { name: /Register source & template/ }))
    fireEvent.click(await screen.findByRole('button', { name: /Sign in with Square/ }))
    await waitFor(() => expect(getSquareAuthorizeUrl).toHaveBeenCalledWith('square_pos_v2', undefined))
  })

  it('re-entry with both source + template pre-existing advances to Connect with a note', async () => {
    // Both writes report "already exists" (409, tolerated) -> the journey must advance, not error.
    vi.mocked(createSourceIfAbsent).mockResolvedValueOnce(false)
    vi.mocked(createMappingTemplateIfAbsent).mockResolvedValueOnce(false)
    renderJourney('/connect/square', TENANT_SNAP)
    fireEvent.click(screen.getByRole('button', { name: /Register source & template/ }))
    await screen.findByRole('button', { name: /Sign in with Square/ })
    expect(screen.getByText(/already registered/i)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('surfaces a genuine (non-409) template error instead of advancing', async () => {
    // A non-409 from the template create is re-thrown by createMappingTemplateIfAbsent; the
    // Register step must show it and stay put (no Connect button).
    vi.mocked(createMappingTemplateIfAbsent).mockRejectedValueOnce(new Error('template boom'))
    renderJourney('/connect/square', TENANT_SNAP)
    fireEvent.click(screen.getByRole('button', { name: /Register source & template/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('template boom')
    expect(screen.queryByRole('button', { name: /Sign in with Square/ })).toBeNull()
  })
})

describe('SquareJourney — PLATFORM persona', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sessionStorage.clear()
  })

  it('requires a tenant selection before Register is enabled', () => {
    renderJourney('/connect/square', PLATFORM_SNAP)
    expect(screen.getByLabelText('Tenant to connect')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Register source & template/ })).toBeDisabled()
  })

  it('threads the selected acted-for tenant through register + mapping-template', async () => {
    renderJourney('/connect/square', PLATFORM_SNAP)
    fireEvent.change(screen.getByLabelText('Tenant to connect'), { target: { value: 'ten-zabka' } })
    fireEvent.click(screen.getByRole('button', { name: /Register source & template/ }))
    await screen.findByRole('button', { name: /Sign in with Square/ })
    expect(createSourceIfAbsent).toHaveBeenCalledWith(
      expect.objectContaining({ source_id: 'square_pos_v2', acting_for_tenant_id: 'ten-zabka' }),
    )
    expect(createMappingTemplateIfAbsent).toHaveBeenCalledWith(
      expect.objectContaining({ template_type: 'snapshot', acting_for_tenant_id: 'ten-zabka' }),
    )
  })

  it('passes the acted-for tenant to the authorize URL', async () => {
    renderJourney('/connect/square', PLATFORM_SNAP)
    fireEvent.change(screen.getByLabelText('Tenant to connect'), { target: { value: 'ten-zabka' } })
    fireEvent.click(screen.getByRole('button', { name: /Register source & template/ }))
    fireEvent.click(await screen.findByRole('button', { name: /Sign in with Square/ }))
    await waitFor(() =>
      expect(getSquareAuthorizeUrl).toHaveBeenCalledWith('square_pos_v2', 'ten-zabka'),
    )
  })

  it('lists distinct tenants from the sources read', () => {
    renderJourney('/connect/square', PLATFORM_SNAP)
    expect(screen.getByRole('option', { name: 'Acme Retail' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Zabka Group' })).toBeInTheDocument()
  })
})

describe('SquareJourney — first-pull affordance (both personas)', () => {
  it('shows run/canonical links when returning connected', () => {
    renderJourney('/connect/square?connected=1&source_id=square_pos_v2&merchant_id=M1', PLATFORM_SNAP)
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
