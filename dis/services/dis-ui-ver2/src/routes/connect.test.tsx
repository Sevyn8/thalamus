import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import type { ReactNode } from 'react'

import { Connect } from './Connect'

// Connect picker: the "Source & method" tile grid. Manual CSV is live (no badge); the other five
// methods carry a muted "Coming soon" marker but stay live buttons — clicking one still opens its
// preview walkthrough (badge is a marker only, never a click block).

function renderConnect(): void {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const tree: ReactNode = (
    <QueryClientProvider client={qc}>
      <Connect />
    </QueryClientProvider>
  )
  render(tree)
}

const NON_CSV_TILES = ['Native connector', 'API pull', 'Webhook push', 'SFTP', 'iPaaS / custom']

function tileByTitle(title: string): HTMLElement {
  return screen.getByText(title).closest('.choice') as HTMLElement
}

describe('Connect picker — Coming soon markers', () => {
  it('badges the five non-CSV tiles and leaves Manual CSV unbadged', () => {
    renderConnect()
    for (const title of NON_CSV_TILES) {
      expect(within(tileByTitle(title)).getByText('Coming soon')).toBeInTheDocument()
    }
    expect(within(tileByTitle('Manual CSV')).queryByText('Coming soon')).toBeNull()
    // exactly five markers across the grid, no more.
    expect(screen.getAllByText('Coming soon')).toHaveLength(5)
  })

  it('renders all six tiles as live (enabled) buttons', () => {
    renderConnect()
    const tiles = ['Manual CSV', ...NON_CSV_TILES].map(tileByTitle)
    expect(tiles).toHaveLength(6)
    for (const tile of tiles) {
      expect(tile.tagName).toBe('BUTTON')
      expect(tile).toBeEnabled()
    }
  })

  it('keeps a badged tile clickable — clicking opens its preview walkthrough', () => {
    renderConnect()
    // Native connector is badged; clicking it must still leave the picker for the PosWizard preview.
    fireEvent.click(screen.getByText('Native connector'))
    expect(screen.queryByText('iPaaS / custom')).toBeNull() // picker tiles gone (lede removed; use a tile as the picker marker)
    // PosWizard preview walkthrough is now on screen.
    expect(screen.getByText(/no live connection is made/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Back/ })).toBeInTheDocument()
  })

  it('keeps another badged tile (SFTP) clickable — click-through is not blocked', () => {
    renderConnect()
    fireEvent.click(screen.getByText('SFTP'))
    // left the picker for SFTP's walkthrough (picker sub-copy gone, back affordance present).
    expect(screen.queryByText('iPaaS / custom')).toBeNull() // picker tiles gone (lede removed; use a tile as the picker marker)
    expect(screen.getByRole('heading', { name: /SFTP isn.t available yet/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Back/ })).toBeInTheDocument()
  })
})
