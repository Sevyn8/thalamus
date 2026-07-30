import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { AuthSnapshot } from '../auth/AuthSnapshot'
import { AuthContext } from '../auth/context'
import type { AuthContextValue } from '../auth/context'
import { Shell } from './Shell'

const TENANT: AuthSnapshot = {
  userId: 'u',
  tenantId: 't_acme9k2l1mn4',
  storeId: 's',
  userType: 'TENANT',
  roles: ['dis:read'],
}

// The Shell now fetches its own tenant name (useTenantSelf), so it needs a QueryClient
// like every route test. retry:false so a fixture miss resolves immediately instead of
// backing off.
function renderShell(authOverrides: Partial<AuthContextValue> = {}) {
  const authValue: AuthContextValue = {
    profile: null,
    status: 'authenticated',
    snapshot: TENANT,
    login: () => Promise.resolve(),
    logout: () => {},
    ...authOverrides,
  }
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <AuthContext.Provider value={authValue}>
        <MemoryRouter initialEntries={['/']}>
          <Routes>
            <Route element={<Shell />}>
              <Route index element={<div>home</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
  )
}

describe('Shell — brand, footer, nav', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('brand reads "Sevyn8" + DIS chip (not Ithina)', () => {
    renderShell()
    expect(screen.getByText('Sevyn8')).toBeInTheDocument()
    expect(screen.getByText('DIS')).toBeInTheDocument()
    expect(screen.queryByText('Ithina')).not.toBeInTheDocument()
  })

  it('footer keeps "Data Ingestion System" and drops "Spectrum Intelligence v4"', () => {
    renderShell()
    expect(screen.getByText('Data Ingestion System')).toBeInTheDocument()
    expect(screen.queryByText(/Spectrum Intelligence/)).not.toBeInTheDocument()
  })

  it('nav shows the reorganized labels in order, with the renames', () => {
    const { container } = renderShell()
    const labels = Array.from(container.querySelectorAll('.nav a')).map((a) =>
      (a.textContent ?? '').replace(/●/g, '').trim(),
    )
    expect(labels).toEqual([
      'Dashboard',
      'Configured Data Sources',
      'Ingestion Runs',
      'Data Quality & History',
      'Connect a Data Source',
      'Data Ingestion Templates',
      'Connector Health',
      'Schema Drift & Changes',
      'Canonical Explorer',
      'Credentials & Secrets',
      'Audit & Version History',
      'Needs Attention',
    ])
    // The old labels are gone.
    expect(screen.queryByText('Data Pipelines')).not.toBeInTheDocument()
    expect(screen.queryByText('Mapping Templates')).not.toBeInTheDocument()
  })

  it('has no count badges on any nav item', () => {
    const { container } = renderShell()
    expect(container.querySelectorAll('.nav a .ct')).toHaveLength(0)
    for (const old of ['24', '6 live', '18', '3']) {
      expect(screen.queryByText(old)).not.toBeInTheDocument()
    }
  })

  it('shows a lock glyph on exactly the 2 premium items, routes unchanged', () => {
    const { container } = renderShell()
    const locks = container.querySelectorAll('.nav a .lock')
    expect(locks).toHaveLength(2)
    const lockedLabels = Array.from(locks).map((l) => (l.closest('a')?.textContent ?? '').replace(/●/g, '').trim())
    // Connector Health is now a normal available surface — no longer locked.
    expect(new Set(lockedLabels)).toEqual(new Set(['Schema Drift & Changes', 'Credentials & Secrets']))
    // Routes unchanged: the locked items still point at their existing paths.
    const byText = (t: string) => screen.getByText(t).closest('a') as HTMLAnchorElement
    // Connector Health is present and unlocked (its route is unchanged, no lock glyph on its link).
    expect(byText('Connector Health').getAttribute('href')).toBe('/connector-health')
    expect(byText('Connector Health').querySelector('.lock')).toBeNull()
    expect(byText('Schema Drift & Changes').getAttribute('href')).toBe('/schema-drift')
    expect(byText('Credentials & Secrets').getAttribute('href')).toBe('/credentials')
    expect(byText('Configured Data Sources').getAttribute('href')).toBe('/pipelines')
    expect(byText('Data Ingestion Templates').getAttribute('href')).toBe('/templates')
  })

  it('shows the "My Sevyn8" launcher link when VITE_CM_LAUNCHER_URL is set', () => {
    vi.stubEnv('VITE_CM_LAUNCHER_URL', 'https://cm.example.test/my-ithina')
    renderShell()
    const link = screen.getByRole('link', { name: /My Sevyn8/ })
    expect(link).toHaveAttribute('href', 'https://cm.example.test/my-ithina')
  })

  it('hides the launcher link when VITE_CM_LAUNCHER_URL is unset', () => {
    vi.stubEnv('VITE_CM_LAUNCHER_URL', '')
    renderShell()
    expect(screen.queryByRole('link', { name: /My Sevyn8/ })).not.toBeInTheDocument()
  })

  it('Sources & Data group lists Data Ingestion Templates directly below Connect a Data Source', () => {
    const { container } = renderShell()
    const groups = Array.from(container.querySelectorAll('.navgrp'))
    const sourcesGroup = groups.find((g) => within(g as HTMLElement).queryByText('Sources & Data'))
    const labels = Array.from((sourcesGroup as HTMLElement).querySelectorAll('.nav a')).map((a) =>
      (a.textContent ?? '').replace(/●/g, '').trim(),
    )
    expect(labels[0]).toBe('Connect a Data Source')
    expect(labels[1]).toBe('Data Ingestion Templates')
  })
})

// -- ledger 21: the signed-in user + the tenant NAME instead of a bare UUID ------------
//
// The topbar used to read "Tenant 019f9d6d-c032-..." and show no user at all. The tenant
// label now comes from identity_mirror via GET /tenant-self and falls back name ->
// display_code -> UUID; the user comes from the Auth0 session client-side.
//
// TENANT here has tenantId 't_acme9k2l1mn4', which is NOT in the fixture map, so these
// exercise the unmirrored path on purpose — the fallback is the part that must not break.

describe('Shell — identity (ledger 21)', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('falls back to the raw tenant id when the mirror has no row', async () => {
    renderShell()
    // LOAD-BEARING: mirror lag must degrade to the UUID, never to blank. A tenant
    // onboarded since the last mirror-sync run legitimately has no row.
    expect(await screen.findByText('t_acme9k2l1mn4')).toBeInTheDocument()
  })

  it('offers a real copy BUTTON with the id in its accessible name', async () => {
    renderShell()
    // A title tooltip cannot be pasted; the person who needs this id is a tenant admin on
    // a support call. It must be a button, and its accessible name must say which id.
    const button = await screen.findByRole('button', { name: /copy tenant id t_acme9k2l1mn4/i })
    expect(button).toBeInTheDocument()
  })

  it('renders no user chip when the session carries no profile', () => {
    renderShell({ profile: null })
    // Absent identity shows nothing rather than a placeholder like "Unknown user".
    expect(screen.queryByText(/@/)).not.toBeInTheDocument()
  })

  it('shows a real name when the profile has one', async () => {
    renderShell({ profile: { name: 'A. Kowalski', email: 'a.kowalski@zabka.pl' } })
    expect(await screen.findByText('A. Kowalski')).toBeInTheDocument()
  })

  it('derives the display name from the email when no name claim exists', async () => {
    // THE EXPECTED PRODUCTION CASE: the shared Auth0 Action stamps no name claim, so this
    // derivation - mirrored from cm-frontend so one person reads the same in both products
    // - is what actually renders for everyone.
    renderShell({ profile: { name: null, email: 'amit@sevyn8.com' } })
    expect(await screen.findByText('Amit')).toBeInTheDocument()
  })

  it('PLATFORM still reads "Scope: All tenants" and gets no tenant chip', () => {
    const platform: AuthSnapshot = { ...TENANT, tenantId: null, userType: 'PLATFORM' }
    renderShell({ snapshot: platform })
    expect(screen.getByText('All tenants')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /copy tenant id/i })).not.toBeInTheDocument()
  })
})
