import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'

import type { AuthSnapshot } from '../auth/AuthSnapshot'
import { AuthContext } from '../auth/context'
import type { AuthContextValue } from '../auth/context'
import { Sources } from './Sources'

// Item 4a: a row click opens a detail drawer of REGISTRY facts only. Honesty guard: the drawer
// must NOT show or imply liveness/last-ingest/health (that is the Connector Health surface, D116).

const TENANT: AuthSnapshot = {
  userId: 'u_acmeuser0001',
  tenantId: 't_acme9k2l1mn4',
  storeId: 's_x',
  userType: 'TENANT',
  roles: ['dis:read'],
}

function renderSources(): void {
  const authValue: AuthContextValue = {
    profile: null,
    status: 'authenticated',
    snapshot: TENANT,
    login: () => Promise.resolve(),
    logout: () => {},
  }
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const tree: ReactNode = (
    <QueryClientProvider client={qc}>
      <AuthContext.Provider value={authValue}>
        <MemoryRouter initialEntries={['/pipelines']}>
          <Sources />
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>
  )
  render(tree)
}

describe('Sources detail drawer (Item 4a — registry facts, no liveness)', () => {
  it('opens from a row click with registry fields and NO liveness fields', async () => {
    renderSources()
    const cell = await screen.findByText('Manual Csv Upload')
    await userEvent.setup().click(cell.closest('tr') as HTMLElement)

    const dialog = await screen.findByRole('dialog', { name: 'Data source detail' })
    const d = within(dialog)
    // registry field labels present.
    const labels = d.getAllByRole('term').map((t) => t.textContent ?? '')
    expect(labels).toEqual(
      expect.arrayContaining(['Source ID', 'Display name', 'Method', 'Store', 'Schedule', 'Status']),
    )
    // HONESTY GUARD: no liveness/last-ingest/health field labels (these belong to Connector Health).
    expect(labels.some((l) => /last seen|last run|last ingest|health|freshness|velocity/i.test(l))).toBe(false)
    // the drawer states the guard explicitly.
    expect(d.getByText(/Runtime health.*Connector Health/i)).toBeInTheDocument()
    // a real registry value renders (the source id).
    expect(d.getAllByText('manual_csv_upload').length).toBeGreaterThan(0)
  })

  it('closes on Escape', async () => {
    renderSources()
    const cell = await screen.findByText('Manual Csv Upload')
    const user = userEvent.setup()
    await user.click(cell.closest('tr') as HTMLElement)
    const dialog = await screen.findByRole('dialog', { name: 'Data source detail' })
    expect(dialog).toHaveAttribute('aria-hidden', 'false')
    await user.keyboard('{Escape}')
    expect(dialog).toHaveAttribute('aria-hidden', 'true')
  })
})
