import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'

import { AuthProvider } from '../auth/AuthProvider'
import { PERSONAS } from '../auth/dev/personas'
import { signStubToken } from '../auth/dev/signStubToken'
import { writeToken } from '../auth/storage'
import { AppRoutes } from './AppRoutes'

// Drives auth through the STORAGE seam, not the /dev/login button; the button path
// (runtime signStubToken minting) is covered by the browser smoke / E2E. Here: a minted
// stub token (sub = persona.sub) restored by AuthProvider lands the user on the Shell +
// Dashboard (index); logout (Shell topbar) returns to /dev/login. Both personas reach
// the Dashboard.

// Dashboard + Shell read via TanStack Query (fixture mode), so the tree needs a QueryClient.
function renderApp() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <MemoryRouter initialEntries={['/']}>
          <AppRoutes />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  )
}

describe('DevLogin session restore', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('restores session per persona and reflects the shell on switch', async () => {
    const user = userEvent.setup()
    const tenant = PERSONAS.find((p) => p.id === 'tenant')
    const ops = PERSONAS.find((p) => p.id === 'ops')
    if (tenant === undefined || ops === undefined) {
      throw new Error('expected tenant and ops personas')
    }

    // Tenant: seed a minted stub token via the storage seam; AuthProvider restores it and the
    // Shell + Dashboard render at the index.
    writeToken(await signStubToken(tenant))
    const first = renderApp()
    expect(await screen.findByRole('heading', { name: 'Operations Dashboard' })).toBeInTheDocument()

    // Logout (Shell topbar) clears the session and redirects to the public /dev/login.
    await user.click(screen.getByRole('button', { name: /log out/i }))
    expect(await screen.findByRole('heading', { name: /dev login/i })).toBeInTheDocument()
    first.unmount()

    // Switch: restore the ops session; the ops persona also lands on the Dashboard.
    writeToken(await signStubToken(ops))
    renderApp()
    expect(await screen.findByRole('heading', { name: 'Operations Dashboard' })).toBeInTheDocument()
  })
})
