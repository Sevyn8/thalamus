import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router'

import type { AuthSnapshot } from '../auth/AuthSnapshot'
import { AuthContext } from '../auth/context'
import type { AuthContextValue } from '../auth/context'
import { SourceTemplates } from './SourceTemplates'

// Item 3: the Data Ingestion Templates rows are whole-row navigable (mouse), while the inner
// template-name <Link> stays the keyboard focus stop + real href. Clicking row chrome (not the
// link) navigates to the template detail; the Link is still present, and the row has no tabIndex
// (which would double the keyboard tab stop for the same action).

const TENANT: AuthSnapshot = {
  userId: 'u_acmeuser0001',
  tenantId: 't_acme9k2l1mn4',
  storeId: 's_x',
  userType: 'TENANT',
  roles: ['dis:read'],
}

function renderTemplates(): void {
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
        <MemoryRouter initialEntries={['/templates']}>
          <Routes>
            <Route path="/templates" element={<SourceTemplates />} />
            <Route path="/templates/:id" element={<div>TEMPLATE DETAIL PAGE</div>} />
          </Routes>
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>
  )
  render(tree)
}

describe('SourceTemplates — whole-row navigation (Item 3)', () => {
  it('navigates to the template detail when clicking the row (not the name link)', async () => {
    renderTemplates()
    const link = (await screen.findAllByRole('link'))[0] // the first template-name Link
    const row = link.closest('tr') as HTMLElement
    // the Link is the real href (keyboard focus stop + open-in-new-tab).
    expect(link).toHaveAttribute('href', expect.stringContaining('/templates/'))
    // no duplicate tab stop: the row itself is not tabbable.
    expect(row).not.toHaveAttribute('tabindex')
    // clicking row chrome (the tr, not the link) navigates.
    await userEvent.setup().click(row)
    expect(await screen.findByText('TEMPLATE DETAIL PAGE')).toBeInTheDocument()
  })
})
