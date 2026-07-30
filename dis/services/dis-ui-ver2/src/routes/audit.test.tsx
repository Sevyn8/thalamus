import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'

import type { AuthSnapshot } from '../auth/AuthSnapshot'
import { AuthContext } from '../auth/context'
import type { AuthContextValue } from '../auth/context'
import { Audit } from './Audit'

// Fixture-mode render (no backend): the Audit surface is the mockup's event-log table
// (When · Who · Action · Object · Detail) wired to useAuditEvents (GET /api/v1/audit shape).
// Asserts the columns, a fixture row's non-PII actor (service_name — never an invented person
// name), the outcome-coloured Action badge, and that the outcome filter narrows the list.

const TENANT: AuthSnapshot = {
  userId: 'u_acmeuser0001',
  tenantId: 't_acme9k2l1mn4',
  storeId: 's_x',
  userType: 'TENANT',
  roles: ['dis:read'],
}

function renderAudit(snapshot: AuthSnapshot = TENANT): void {
  const authValue: AuthContextValue = {
    profile: null,
    status: 'authenticated',
    snapshot,
    login: () => Promise.resolve(),
    logout: () => {},
  }
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const tree: ReactNode = (
    <QueryClientProvider client={qc}>
      <AuthContext.Provider value={authValue}>
        <MemoryRouter initialEntries={['/audit']}>
          <Audit />
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>
  )
  render(tree)
}

describe('Audit surface — event-log table (fixture mode)', () => {
  it('renders the mockup columns and fixture rows with a non-PII actor', async () => {
    renderAudit()
    expect(
      await screen.findByRole('heading', { name: 'Audit & Version History', level: 1 }),
    ).toBeInTheDocument()
    // the mockup's five columns (await the async query settling into the table).
    expect(await screen.findByRole('columnheader', { name: 'When' })).toBeInTheDocument()
    for (const col of ['Who', 'Action', 'Object', 'Detail']) {
      expect(screen.getByRole('columnheader', { name: col })).toBeInTheDocument()
    }
    // Who = the non-PII actor (service_name), NOT an invented person name.
    expect(screen.getAllByText('streaming-consumer').length).toBeGreaterThan(0)
    expect(screen.getAllByText('csv-ingest-worker').length).toBeGreaterThan(0)
    expect(screen.queryByText('Amit Boni')).not.toBeInTheDocument()
    // Action = a stage badge (coloured by outcome).
    expect(screen.getByText('CANONICAL_WRITTEN')).toBeInTheDocument()
    // Detail surfaces a failure message for the quarantined disposition row.
    expect(screen.getByText('column price failed numeric cast')).toBeInTheDocument()
  })

  it('narrows the list when the outcome filter is set', async () => {
    renderAudit()
    // All six fixture rows present initially (CANONICAL_WRITTEN success is one of them).
    expect(await screen.findByText('CANONICAL_WRITTEN')).toBeInTheDocument()
    expect(screen.getByText('MAPPING_EXECUTION')).toBeInTheDocument() // the 'retried' row

    // Filter to duplicate: only the INGRESS_PUBLISHED (duplicate) row remains.
    await userEvent.setup().selectOptions(screen.getByRole('combobox', { name: 'Outcome' }), 'duplicate')
    expect(await screen.findByText('INGRESS_PUBLISHED')).toBeInTheDocument()
    expect(screen.queryByText('CANONICAL_WRITTEN')).not.toBeInTheDocument()
    expect(screen.queryByText('MAPPING_EXECUTION')).not.toBeInTheDocument()
  })
})

describe('Audit detail drawer (Item 4b)', () => {
  it('opens from a row click with trace/outcome/failure and event_data as key/values', async () => {
    renderAudit()
    // open the failure row (its detail carries a failure message + is the richest event).
    const cell = await screen.findByText('column price failed numeric cast')
    await userEvent.setup().click(cell.closest('tr') as HTMLElement)

    const dialog = await screen.findByRole('dialog', { name: 'Audit event detail' })
    const d = within(dialog)
    // servable event fields (labels).
    const labels = d.getAllByRole('term').map((t) => t.textContent ?? '')
    expect(labels).toEqual(
      expect.arrayContaining(['Actor', 'Stage', 'Scope', 'Outcome', 'Trace id', 'Prior trace', 'Row count']),
    )
    // trace anchor + the failure block render.
    expect(d.getByText(/column price failed numeric cast/)).toBeInTheDocument()
    // "Event data" section present (arbitrary jsonb bag rendered as key/values, shape not assumed).
    expect(d.getByRole('heading', { name: 'Event data' })).toBeInTheDocument()
  })

  it('renders a success-row event_data key honestly (no assumed shape) and closes on Escape', async () => {
    renderAudit()
    const user = userEvent.setup()
    const cell = await screen.findByText('CANONICAL_WRITTEN')
    await user.click(cell.closest('tr') as HTMLElement)
    const dialog = await screen.findByRole('dialog', { name: 'Audit event detail' })
    // the fixture success event carries event_data { written_to_table: ... } -> shown as a key/value.
    expect(within(dialog).getByText('written_to_table')).toBeInTheDocument()
    expect(dialog).toHaveAttribute('aria-hidden', 'false')
    await user.keyboard('{Escape}')
    expect(dialog).toHaveAttribute('aria-hidden', 'true')
  })
})
