import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import { vi } from 'vitest'

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

import { getCloverAuthorizeUrl } from '../../../lib/dis-ui-server/clover-oauth'
import { createMappingTemplateIfAbsent } from '../../../lib/dis-ui-server/mapping-templates'
import { createSourceIfAbsent } from '../../../lib/dis-ui-server/sources'

const TENANT = { userId: 'u', tenantId: 't', storeId: null, roles: [], userType: 'TENANT' as const }

function render(entry = '/connect/clover'): void {
  renderWithProviders(
    <Routes>
      <Route path="/connect/clover" element={<CloverJourney />} />
      <Route path="/connect" element={<div>SOURCES GRID</div>} />
    </Routes>,
    { snapshot: TENANT, initialEntries: [entry] },
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
})

// -- register ---------------------------------------------------------------------------

test('register creates the source and template with no acted-for tenant', async () => {
  render()
  fireEvent.click(screen.getByRole('button', { name: 'Register source & template' }))
  await screen.findByRole('button', { name: 'Continue to authorise' })
  expect(createSourceIfAbsent).toHaveBeenCalledWith(
    expect.objectContaining({ source_id: 'clover_pos_v1', channel: 'api' }),
  )
  // Self-serve TENANT: the tenant is derived server-side from the Bearer, never a param.
  expect(vi.mocked(createSourceIfAbsent).mock.calls[0][0]).not.toHaveProperty(
    'acting_for_tenant_id',
  )
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
  await waitFor(() => expect(getCloverAuthorizeUrl).toHaveBeenCalledWith('clover_pos_v1'))
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
