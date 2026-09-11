import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import { vi } from 'vitest'

import type { AuthSnapshot } from '../../../auth/AuthSnapshot'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { CloverJourney } from './CloverJourney'

vi.mock('../../../lib/dis-ui-server/sources', () => ({
  createSourceIfAbsent: vi.fn().mockResolvedValue(true),
}))
vi.mock('../../../lib/dis-ui-server/mapping-templates', () => ({
  createMappingTemplateIfAbsent: vi.fn().mockResolvedValue(true),
}))
vi.mock('../../../lib/dis-ui-server/clover-oauth', () => ({
  getCloverAuthorizeUrl: vi.fn().mockResolvedValue({ authorize_url: 'https://cl.test/x', state: 's' }),
}))
// Store reads, the same shape the Square journey's test mocks. Default: one onboarded store
// so it auto-selects (the common sandbox case); individual tests override for multi/empty.
// The PLATFORM cross-tenant read returns a DIFFERENT store, so which query fed the picker is
// visible in the assertions rather than inferred.
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
// The actable-tenant read behind the shared ActedForPicker. Includes a suspended tenant, which
// must be offered-but-unselectable rather than hidden.
const ACTABLE_TENANTS = [
  { tenant_id: 'ten-newco', name: 'Brand New Co', display_code: null, status: 'onboarding' },
  { tenant_id: 'ten-paused', name: 'Paused Partners', display_code: null, status: 'suspended' },
  { tenant_id: 'ten-zabka', name: 'Zabka Group', display_code: null, status: 'active' },
]
vi.mock('../../../lib/dis-ui-server/tenants', () => ({
  useActableTenants: vi.fn(() => ({ data: ACTABLE_TENANTS, isPending: false, isError: false })),
}))

import { getCloverAuthorizeUrl } from '../../../lib/dis-ui-server/clover-oauth'
import { createMappingTemplateIfAbsent } from '../../../lib/dis-ui-server/mapping-templates'
import { createSourceIfAbsent } from '../../../lib/dis-ui-server/sources'
import { useStoresOnboarded } from '../../../lib/dis-ui-server/stores'

const TENANT = { userId: 'u', tenantId: 't', storeId: null, roles: [], userType: 'TENANT' as const }
const PLATFORM = {
  userId: 'ops',
  tenantId: null,
  storeId: null,
  roles: ['dis:ops'],
  userType: 'PLATFORM' as const,
}

function render(entry = '/connect/clover', snapshot: AuthSnapshot = TENANT): void {
  renderWithProviders(
    <Routes>
      <Route path="/connect/clover" element={<CloverJourney />} />
      <Route path="/connect" element={<div>SOURCES GRID</div>} />
    </Routes>,
    { snapshot, initialEntries: [entry] },
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
  vi.mocked(useStoresOnboarded).mockReturnValue({
    data: [{ store_id: 's1', name: 'Buc-ees Katy', store_code: 'AMB-001', status: 'active' }],
    isPending: false,
  } as never)
})

// -- register ---------------------------------------------------------------------------

test('register creates the source and template with no acted-for tenant', async () => {
  render()
  fireEvent.click(screen.getByRole('button', { name: 'Register source & template' }))
  await screen.findByRole('button', { name: 'Continue to authorise' })
  expect(createSourceIfAbsent).toHaveBeenCalledWith(
    expect.objectContaining({
      source_id: 'clover_pos_v1',
      channel: 'api',
      // ConnectorTrigger.store_id is required, so a source with no store cannot be pulled.
      store_id: 'AMB-001',
    }),
  )
  // Self-serve TENANT: the tenant is derived server-side from the Bearer, never a param.
  // Asserted against the WIRE, not key-presence: the journey now always passes the field and
  // lets it be undefined for a TENANT (the same shape as Square), and JSON.stringify drops an
  // undefined value — so "never a param" is a statement about the serialized body.
  const body = vi.mocked(createSourceIfAbsent).mock.calls[0][0]
  expect(body.acting_for_tenant_id).toBeUndefined()
  expect(JSON.stringify(body)).not.toContain('acting_for_tenant_id')
  expect(createMappingTemplateIfAbsent).toHaveBeenCalledWith(
    expect.objectContaining({ template_type: 'snapshot', source_id: 'clover_pos_v1' }),
  )
})

test('the template declares sku_source as ignored rather than omitting it', async () => {
  render()
  fireEvent.click(screen.getByRole('button', { name: 'Register source & template' }))
  await screen.findByRole('button', { name: 'Continue to authorise' })
  const columns = vi.mocked(createMappingTemplateIfAbsent).mock.calls[0][0].columns
  const bySrc = Object.fromEntries(columns.map((c) => [c.src_key, c.dest_key]))
  // Bronze-only provenance with no canonical column: seen and deliberately not mapped.
  expect(bySrc['sku_source']).toBe('__ignore__')
  // Mandatory snapshot coverage, or the BFF's semantic gate 400s and the journey breaks.
  expect(bySrc['sku_id']).toBe('sku_id')
  expect(bySrc['product_name']).toBe('product_name')
  expect(bySrc['current_retail_price']).toBe('current_retail_price')
})

test('a register failure shows client-facing copy with no error code', async () => {
  vi.mocked(createSourceIfAbsent).mockRejectedValueOnce(
    Object.assign(new Error('boom'), { code: 'tenant_scope', status: 403 }),
  )
  render()
  fireEvent.click(screen.getByRole('button', { name: 'Register source & template' }))
  const alert = await screen.findByRole('alert')
  // D8: what happened and what to do. No code, no 403, no first person.
  expect(alert.textContent).toBe('The Clover source could not be set up. Try again in a moment.')
  expect(alert.textContent).not.toMatch(/tenant_scope|403|I /)
})

// -- install: a SIGNPOST, so both doors advance and NEITHER writes ------------------------

async function reachInstall(): Promise<void> {
  render()
  fireEvent.click(screen.getByRole('button', { name: 'Register source & template' }))
  await screen.findByRole('button', { name: 'Continue to authorise' })
  vi.clearAllMocks() // ignore the register writes; we are asserting about the install step
}

test('install offers two doors and names the different-person risk', async () => {
  await reachInstall()
  expect(screen.getByRole('button', { name: 'Continue to authorise' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Open App Market' })).toBeInTheDocument()
  expect(screen.getByText(/may need a different person/i)).toBeInTheDocument()
})

test('the direct door advances to connect and writes nothing', async () => {
  await reachInstall()
  fireEvent.click(screen.getByRole('button', { name: 'Continue to authorise' }))
  expect(await screen.findByRole('button', { name: 'Sign in with Clover' })).toBeInTheDocument()
  // Nothing can be verified at install - we do not know the merchant yet - so nothing is
  // written and no vendor call is made. Connect is the only verification.
  expect(createSourceIfAbsent).not.toHaveBeenCalled()
  expect(createMappingTemplateIfAbsent).not.toHaveBeenCalled()
  expect(getCloverAuthorizeUrl).not.toHaveBeenCalled()
  expect(sessionStorage.length).toBe(0)
})

test('the app-market door opens the listing AND advances, writing nothing', async () => {
  const open = vi.fn()
  vi.stubGlobal('open', open)
  try {
    await reachInstall()
    fireEvent.click(screen.getByRole('button', { name: 'Open App Market' }))
    expect(open).toHaveBeenCalledWith(
      expect.stringContaining('appmarket'),
      '_blank',
      'noopener,noreferrer',
    )
    // Both doors lead onward: the listing opens in a new tab, this one moves to Connect.
    expect(await screen.findByRole('button', { name: 'Sign in with Clover' })).toBeInTheDocument()
    expect(createSourceIfAbsent).not.toHaveBeenCalled()
    expect(getCloverAuthorizeUrl).not.toHaveBeenCalled()
    expect(sessionStorage.length).toBe(0)
  } finally {
    vi.unstubAllGlobals()
  }
})

// -- connect + resume ----------------------------------------------------------------------

test('connect requests the authorize url for clover_pos_v1', async () => {
  await reachInstall()
  fireEvent.click(screen.getByRole('button', { name: 'Continue to authorise' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Sign in with Clover' }))
  // undefined acted-for for a TENANT (the field is always passed, always undefined here) —
  // the same call shape as the Square journey.
  await waitFor(() =>
    expect(getCloverAuthorizeUrl).toHaveBeenCalledWith('clover_pos_v1', undefined),
  )
})

test('a resume from launch opens at connect and names the merchant', () => {
  // The installed-but-not-authorised branch: the tenant needs to see the install worked.
  render('/connect/clover?step=connect&merchant_id=0RKKDBMKPAH71')
  expect(screen.getByRole('button', { name: 'Sign in with Clover' })).toBeInTheDocument()
  expect(screen.getByText(/0RKKDBMKPAH71/)).toBeInTheDocument()
})

test('a completed connect opens at the terminal step', () => {
  render('/connect/clover?connected=1&source_id=clover_pos_v1&merchant_id=0RKKDBMKPAH71')
  expect(screen.getByText(/Clover is connected/)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'View Ingestion Runs' })).toHaveAttribute(
    'href',
    '/ingestion-runs',
  )
  // Terminal: no accent forward action anywhere on the panel.
  expect(document.querySelectorAll('.btn.pri')).toHaveLength(0)
})


// -- store selection: the same pattern as Square, not a Clover variant -------------------

test('a single onboarded store auto-selects and Register is enabled', () => {
  render()
  expect(screen.getByRole('option', { name: /AMB-001/ })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Register source & template' })).toBeEnabled()
})

test('multiple stores require an explicit pick before Register enables', () => {
  vi.mocked(useStoresOnboarded).mockReturnValue({
    data: [
      { store_id: 's1', name: 'Store A', store_code: 'AMB-001', status: 'active' },
      { store_id: 's2', name: 'Store B', store_code: 'AMB-002', status: 'active' },
    ],
    isPending: false,
  } as never)
  render()
  expect(screen.getByRole('button', { name: 'Register source & template' })).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Store to connect'), { target: { value: 'AMB-002' } })
  expect(screen.getByRole('button', { name: 'Register source & template' })).toBeEnabled()
})

test('a TENANT caller sees no tenant picker at all', () => {
  render()
  expect(screen.queryByLabelText('Tenant to connect')).toBeNull()
})

test('a store with no store_code is not selectable', () => {
  // store_code IS the source's store_id; a NULL code cannot be a source key.
  vi.mocked(useStoresOnboarded).mockReturnValue({
    data: [{ store_id: 's1', name: 'Codeless', store_code: null, status: 'active' }],
    isPending: false,
  } as never)
  render()
  expect(screen.getByText(/No onboarded store with a store code/i)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Register source & template' })).toBeDisabled()
})

test('no stores at all disables Register with a hint rather than failing later', () => {
  vi.mocked(useStoresOnboarded).mockReturnValue({ data: [], isPending: false } as never)
  render()
  expect(screen.getByText(/No onboarded store with a store code/i)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Register source & template' })).toBeDisabled()
})

// -- acted-for onboarding: the PLATFORM persona this journey previously had no path for -----
//
// Before this, the journey had NO tenant picker and passed a hardcoded null to the cross-tenant
// store read. react-query reports a disabled query as pending forever, so a PLATFORM caller sat
// on "Loading stores..." with no error and no way forward, and a register would have 403'd at
// resolve_acted_for even if they had got past it.

describe('CloverJourney — PLATFORM persona', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sessionStorage.clear()
  })

  it('shows the tenant picker and no store picker until a tenant is chosen', () => {
    render('/connect/clover', PLATFORM)
    expect(screen.getByLabelText('Tenant to connect')).toBeInTheDocument()
    // The cross-tenant store read is gated on the selection, so there is nothing to show yet —
    // and, critically, no indefinite "Loading stores...".
    expect(screen.queryByLabelText('Store to connect')).toBeNull()
    expect(screen.queryByText(/Loading stores/i)).toBeNull()
    expect(screen.getByRole('button', { name: 'Register source & template' })).toBeDisabled()
  })

  it('lists a tenant with no sources yet, and a suspended one disabled', () => {
    render('/connect/clover', PLATFORM)
    // The onboarding case: this journey has never registered a source for ten-newco, and the
    // list comes from the tenant mirror, so it is offered anyway.
    expect(screen.getByRole('option', { name: 'Brand New Co' })).toBeInTheDocument()
    const suspended = screen.getByRole('option', { name: 'Paused Partners — suspended' })
    expect(suspended).toBeInTheDocument()
    expect(suspended).toBeDisabled()
  })

  it('reveals the acted-for tenant stores once a tenant is chosen', () => {
    render('/connect/clover', PLATFORM)
    fireEvent.change(screen.getByLabelText('Tenant to connect'), { target: { value: 'ten-zabka' } })
    expect(screen.getByLabelText('Store to connect')).toBeInTheDocument()
    // ZAB-001 comes from the cross-tenant read, not the token-tenant one (AMB-001) — proof the
    // PLATFORM branch is what fired.
    expect(screen.getByRole('option', { name: /ZAB-001/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Register source & template' })).toBeEnabled()
  })

  it('threads the acted-for tenant through register, template and authorize-url', async () => {
    render('/connect/clover', PLATFORM)
    fireEvent.change(screen.getByLabelText('Tenant to connect'), { target: { value: 'ten-zabka' } })
    fireEvent.click(screen.getByRole('button', { name: 'Register source & template' }))
    await screen.findByRole('button', { name: 'Continue to authorise' })
    expect(createSourceIfAbsent).toHaveBeenCalledWith(
      expect.objectContaining({
        source_id: 'clover_pos_v1',
        acting_for_tenant_id: 'ten-zabka',
        store_id: 'ZAB-001',
      }),
    )
    expect(createMappingTemplateIfAbsent).toHaveBeenCalledWith(
      expect.objectContaining({ template_type: 'snapshot', acting_for_tenant_id: 'ten-zabka' }),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Continue to authorise' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Sign in with Clover' }))
    await waitFor(() =>
      expect(getCloverAuthorizeUrl).toHaveBeenCalledWith('clover_pos_v1', 'ten-zabka'),
    )
  })

  it('seeds the picker from the resume hint after a bounce back to Connect', () => {
    // Clover's installed-but-not-authorised branch returns at Connect; stepping BACK to Register
    // must not find the tenant blank.
    sessionStorage.setItem(
      'clover.connect.pending',
      JSON.stringify({ source_id: 'clover_pos_v1', acting_for_tenant_id: 'ten-zabka' }),
    )
    render('/connect/clover?step=connect&merchant_id=0RKKDBMKPAH71', PLATFORM)
    // Step back via the rail (its accessible name is the step number + title + description).
    fireEvent.click(screen.getByRole('button', { name: /Register/ }))
    expect(screen.getByLabelText('Tenant to connect')).toHaveValue('ten-zabka')
  })
})
