import { fireEvent, screen } from '@testing-library/react'
import { Route, Routes } from 'react-router'

import { renderWithProviders } from '../test/renderWithProviders'
import { Connect } from './Connect'

// Connect: the catalog-driven source-card grid (S3). Each source is its own card; active cards
// navigate to their journey route, coming-soon cards are badged and non-navigable. The old
// transport-method tiles + the PosWizard preview are retired.

const SNAP = { userId: 'u', tenantId: 't', storeId: null, roles: [], userType: 'TENANT' as const }

function renderConnect(): void {
  renderWithProviders(
    <Routes>
      <Route path="/connect" element={<Connect />} />
      <Route path="/connect/square" element={<div>SQUARE JOURNEY</div>} />
      <Route path="/connect/clover" element={<div>CLOVER JOURNEY</div>} />
      <Route path="/connect/csv" element={<div>CSV WIZARD</div>} />
    </Routes>,
    { snapshot: SNAP, initialEntries: ['/connect'] },
  )
}

function cardByName(name: string): HTMLElement {
  return screen.getByText(name).closest('.choice') as HTMLElement
}

describe('Connect — source-card grid', () => {
  it('renders the four source cards', () => {
    renderConnect()
    for (const name of ['Manual CSV', 'Square', 'Clover', 'Shopify']) {
      expect(cardByName(name)).toBeInTheDocument()
    }
  })

  it('badges only the coming-soon cards (Shopify)', () => {
    // Clover left the coming-soon set when its connect journey landed (C3).
    renderConnect()
    expect(screen.getAllByText('Coming soon')).toHaveLength(1)
    expect(cardByName('Shopify').querySelector('.choice__soon')).not.toBeNull()
    expect(cardByName('Manual CSV').querySelector('.choice__soon')).toBeNull()
    expect(cardByName('Square').querySelector('.choice__soon')).toBeNull()
    expect(cardByName('Clover').querySelector('.choice__soon')).toBeNull()
  })

  it('enables active cards and disables coming-soon cards', () => {
    renderConnect()
    expect(cardByName('Manual CSV')).toBeEnabled()
    expect(cardByName('Square')).toBeEnabled()
    expect(cardByName('Clover')).toBeEnabled()
    expect(cardByName('Shopify')).toBeDisabled()
  })

  it('navigates to the Clover journey when the Clover card is clicked', () => {
    renderConnect()
    fireEvent.click(cardByName('Clover'))
    expect(screen.getByText('CLOVER JOURNEY')).toBeInTheDocument()
  })

  it('navigates to the Square journey when the Square card is clicked', () => {
    renderConnect()
    fireEvent.click(cardByName('Square'))
    expect(screen.getByText('SQUARE JOURNEY')).toBeInTheDocument()
  })

  it('navigates to the CSV wizard when the Manual CSV card is clicked', () => {
    renderConnect()
    fireEvent.click(cardByName('Manual CSV'))
    expect(screen.getByText('CSV WIZARD')).toBeInTheDocument()
  })

  it('has no legacy method tiles', () => {
    renderConnect()
    for (const gone of ['API pull', 'Webhook push', 'SFTP', 'iPaaS / custom', 'Native connector']) {
      expect(screen.queryByText(gone)).toBeNull()
    }
  })
})
