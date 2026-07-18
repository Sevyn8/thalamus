import { render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { describe, expect, it } from 'vitest'

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

function renderShell() {
  const authValue: AuthContextValue = {
    status: 'authenticated',
    snapshot: TENANT,
    login: () => Promise.resolve(),
    logout: () => {},
  }
  return render(
    <AuthContext.Provider value={authValue}>
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route element={<Shell />}>
            <Route index element={<div>home</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
  )
}

describe('Shell — brand, footer, nav', () => {
  it('brand reads "Ithina" + DIS chip (not SEVYN8)', () => {
    renderShell()
    expect(screen.getByText('Ithina')).toBeInTheDocument()
    expect(screen.getByText('DIS')).toBeInTheDocument()
    expect(screen.queryByText('SEVYN8')).not.toBeInTheDocument()
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
