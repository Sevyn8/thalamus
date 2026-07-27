import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import { vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'
import { SquareJourney } from './SquareJourney'

// Mock the write/connect seams + the actable-tenant read (the tenant picker). tenant-label
// stays real.
//
// THE TWO TENANT FIXTURES ARE A MATCHED PAIR AND THE MISMATCH IS THE POINT. The picker is fed
// by the tenant mirror (ACTABLE_TENANTS); the sources list (FLEET_SOURCES) is the read it used
// to be derived from, and it does NOT contain ten-newco. So an assertion that ten-newco appears
// in the picker is a live negative control: reverting the picker to the sources derivation
// fails it, which is exactly the onboarding bug this replaced (a tenant with no sources yet
// could never be selected, so nobody could connect its FIRST source).
const FLEET_SOURCES = [
  { tenant_id: 'ten-acme', tenant_name: 'Acme Retail' },
  { tenant_id: 'ten-zabka', tenant_name: 'Zabka Group' },
]
const ACTABLE_TENANTS = [
  { tenant_id: 'ten-acme', name: 'Acme Retail', display_code: null, status: 'active' },
  // Freshly CM-onboarded: absent from FLEET_SOURCES, so it exists ONLY in the mirror.
  { tenant_id: 'ten-newco', name: 'Brand New Co', display_code: null, status: 'onboarding' },
  { tenant_id: 'ten-paused', name: 'Paused Partners', display_code: null, status: 'suspended' },
  { tenant_id: 'ten-zabka', name: 'Zabka Group', display_code: null, status: 'active' },
]

// useSources is no longer read by the journey; the mock stays because the fixture above is the
// negative control described there. Do not delete it as "unused" without deleting that proof.
vi.mock('../../../lib/dis-ui-server/sources', () => ({
  createSourceIfAbsent: vi.fn().mockResolvedValue(true),
  useSources: vi.fn(() => ({ data: FLEET_SOURCES, isPending: false })),
}))
vi.mock('../../../lib/dis-ui-server/tenants', () => ({
  useActableTenants: vi.fn(() => ({
    data: ACTABLE_TENANTS,
    isPending: false,
    isError: false,
  })),
}))
vi.mock('../../../lib/dis-ui-server/mapping-templates', () => ({
  createMappingTemplateIfAbsent: vi.fn().mockResolvedValue(true),
}))
vi.mock('../../../lib/dis-ui-server/square-oauth', () => ({
  getSquareAuthorizeUrl: vi.fn().mockResolvedValue({ authorize_url: 'https://sq.test/x', state: 's' }),
}))
// Store reads: TENANT via /stores-onboarded, PLATFORM via the acted-for cross-tenant read.
// Each returns a single store so it auto-selects (the common sandbox case).
vi.mock('../../../lib/dis-ui-server/stores', () => ({
  useStoresOnboarded: vi.fn(() => ({
    data: [{ store_id: 's1', name: 'Buc-ees Katy', store_code: 'AMB-001', status: 'active' }],
    isPending: false,
  })),
  useStoresOnboardedForTenant: vi.fn(() => ({
    data: [{ store_id: 's2', name: 'Zabka #1', store_code: 'ZAB-001', status: 'active' }],
    isPending: false,
  })),
}))

import { createMappingTemplateIfAbsent } from '../../../lib/dis-ui-server/mapping-templates'
import { createSourceIfAbsent } from '../../../lib/dis-ui-server/sources'
import { getSquareAuthorizeUrl } from '../../../lib/dis-ui-server/square-oauth'
import { useStoresOnboarded } from '../../../lib/dis-ui-server/stores'

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
      expect.objectContaining({
        source_id: 'square_pos_v2',
        acting_for_tenant_id: undefined,
        store_id: 'AMB-001', // the real onboarded store, auto-selected (no more W-001 hardcode)
      }),
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
      expect.objectContaining({
        source_id: 'square_pos_v2',
        acting_for_tenant_id: 'ten-zabka',
        store_id: 'ZAB-001', // the acted-for tenant's store, from the cross-tenant read
      }),
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

  it('lists every actable tenant, INCLUDING one with no sources yet', () => {
    renderJourney('/connect/square', PLATFORM_SNAP)
    expect(screen.getByRole('option', { name: 'Acme Retail' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Zabka Group' })).toBeInTheDocument()
    // The onboarding case: ten-newco is absent from FLEET_SOURCES, so the old sources-derived
    // picker could not offer it and its first source could never be connected.
    expect(screen.getByRole('option', { name: 'Brand New Co' })).toBeInTheDocument()
  })

  it('shows a suspended tenant, disabled and saying why', () => {
    renderJourney('/connect/square', PLATFORM_SNAP)
    // Present rather than filtered out (an absent row explains nothing), unselectable, and the
    // status is in the label so the reason is visible.
    const suspended = screen.getByRole('option', { name: 'Paused Partners — suspended' })
    expect(suspended).toBeInTheDocument()
    expect(suspended).toBeDisabled()
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

describe('SquareJourney — store selection (PLATFORM)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sessionStorage.clear()
  })

  it('hides the store picker until a tenant is selected, then shows the acted-for stores', () => {
    renderJourney('/connect/square', PLATFORM_SNAP)
    // No tenant chosen yet -> the cross-tenant store read is gated, no picker.
    expect(screen.queryByLabelText('Store to connect')).toBeNull()
    fireEvent.change(screen.getByLabelText('Tenant to connect'), { target: { value: 'ten-zabka' } })
    expect(screen.getByLabelText('Store to connect')).toBeInTheDocument()
    expect(screen.getByRole('option', { name: /ZAB-001/ })).toBeInTheDocument()
  })
})

describe('SquareJourney — store selection (TENANT)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sessionStorage.clear()
    // Default: one onboarded store (auto-selects). Individual tests override for multi/empty.
    vi.mocked(useStoresOnboarded).mockReturnValue({
      data: [{ store_id: 's1', name: 'Buc-ees Katy', store_code: 'AMB-001', status: 'active' }],
      isPending: false,
    } as never)
  })

  it('shows the store picker with the real onboarded store', () => {
    renderJourney('/connect/square', TENANT_SNAP)
    expect(screen.getByLabelText('Store to connect')).toBeInTheDocument()
    expect(screen.getByRole('option', { name: /AMB-001/ })).toBeInTheDocument()
  })

  it('requires an explicit pick when multiple stores exist (Register disabled until chosen)', () => {
    vi.mocked(useStoresOnboarded).mockReturnValue({
      data: [
        { store_id: 's1', name: 'Store A', store_code: 'AMB-001', status: 'active' },
        { store_id: 's2', name: 'Store B', store_code: 'AMB-002', status: 'active' },
      ],
      isPending: false,
    } as never)
    renderJourney('/connect/square', TENANT_SNAP)
    expect(screen.getByRole('button', { name: /Register source & template/ })).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Store to connect'), { target: { value: 'AMB-002' } })
    expect(screen.getByRole('button', { name: /Register source & template/ })).toBeEnabled()
  })

  it('disables Register with a hint when no store has a store code', () => {
    vi.mocked(useStoresOnboarded).mockReturnValue({ data: [], isPending: false } as never)
    renderJourney('/connect/square', TENANT_SNAP)
    expect(screen.getByText(/No onboarded store with a store code/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Register source & template/ })).toBeDisabled()
  })
})
