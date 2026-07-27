import { cleanup, screen } from '@testing-library/react'
import { Route, Routes } from 'react-router'

import { renderWithProviders } from '../../test/renderWithProviders'
import { JourneyShell } from './JourneyShell'
import type { JourneyDefinition } from './journey'

// The shell is the SPEC for connect-journey chrome (D1), so the test that matters is that
// two different vendors get the SAME chrome from it. Any divergence here is a defect rather
// than a variation, which is exactly why the component exists.

const SNAP = { userId: 'u', tenantId: 't', storeId: null, roles: [], userType: 'TENANT' as const }

function definition(vendorName: string): JourneyDefinition {
  return {
    vendorName,
    step: 0,
    onJump: () => {},
    error: null,
    steps: [
      {
        kind: 'gate',
        meta: { title: 'Register', desc: 'Source & mapping template' },
        body: <p className="sub">body one</p>,
        action: {
          label: 'Register source & template',
          runningLabel: 'Registering...',
          running: false,
          onAct: () => {},
        },
      },
      {
        kind: 'terminal',
        meta: { title: 'First pull', desc: 'Verify data lands' },
        body: <p className="sub">body two</p>,
        links: [{ label: 'View Ingestion Runs', to: '/ingestion-runs' }],
      },
    ],
  }
}

function render(journey: JourneyDefinition): void {
  renderWithProviders(
    <Routes>
      <Route path="/j" element={<JourneyShell journey={journey} />} />
      <Route path="/connect" element={<div>SOURCES GRID</div>} />
    </Routes>,
    { snapshot: SNAP, initialEntries: ['/j'] },
  )
}

function chromeShape(): string[] {
  // The chrome, reduced to what a user actually perceives: headings, rail entries, the
  // forward action, and the footer. Vendor name is deliberately excluded - it is the ONE
  // thing that legitimately differs.
  return [
    ...screen.getAllByRole('heading').map((h) => `h:${h.textContent}`),
    ...screen.getAllByRole('button').map((b) => `btn:${b.textContent}`),
  ]
}

test('the shell renders identical chrome for two different vendors', () => {
  render(definition('Square'))
  const square = chromeShape()
  screen.getByRole('heading', { name: 'Connect Square' })

  cleanup()

  render(definition('Clover'))
  const clover = chromeShape()
  screen.getByRole('heading', { name: 'Connect Clover' })

  // Everything except the vendor-named page head is byte-identical.
  const strip = (entries: string[]) => entries.filter((e) => !e.startsWith('h:Connect '))
  expect(strip(clover)).toEqual(strip(square))
})

test('a gate step renders exactly one accent forward action', () => {
  render(definition('Square'))
  const accent = document.querySelectorAll('.btn.pri')
  expect(accent).toHaveLength(1)
  expect(accent[0].textContent).toBe('Register source & template')
})

test('a gate action shows its running label and is disabled while running', () => {
  const journey = definition('Square')
  const gate = journey.steps[0]
  if (gate.kind !== 'gate') throw new Error('fixture drift')
  gate.action.running = true
  render(journey)
  expect(screen.getByRole('button', { name: 'Registering...' })).toBeDisabled()
})

test('a terminal step renders no accent action, only links', () => {
  const journey = { ...definition('Square'), step: 1 }
  render(journey)
  expect(document.querySelectorAll('.btn.pri')).toHaveLength(0)
  expect(screen.getByRole('link', { name: 'View Ingestion Runs' })).toHaveAttribute(
    'href',
    '/ingestion-runs',
  )
})

test('the terminal step draws exactly one footer rule', () => {
  // The defect this shell was built on top of: the terminal step used to wrap its links in
  // .wizfoot as well as the Back row, drawing two horizontal rules.
  render({ ...definition('Square'), step: 1 })
  expect(document.querySelectorAll('.wizfoot')).toHaveLength(1)
})

test('no alert renders when there is no error', () => {
  render(definition('Square'))
  expect(screen.queryByRole('alert')).toBeNull()
})

test('the error line and the re-entry note render as distinct roles', () => {
  render({ ...definition('Square'), error: 'Something to fix.', note: 'Already registered.' })
  expect(screen.getByRole('alert')).toHaveTextContent('Something to fix.')
  expect(screen.getByRole('status')).toHaveTextContent('Already registered.')
})
