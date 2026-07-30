import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router'

import type { AuthSnapshot } from '../auth/AuthSnapshot'
import { AuthContext } from '../auth/context'
import type { AuthContextValue } from '../auth/context'
import type { MappingTemplateDetail } from '../lib/dis-ui-server/mapping-templates'
import { Dashboard } from './Dashboard'
import { DataQuality } from './DataQuality'
import { TemplateDetail } from './TemplateDetail'

const TENANT: AuthSnapshot = { userId: 'u_acmeuser0001', tenantId: 't_acme9k2l1mn4', storeId: 's_x', userType: 'TENANT', roles: ['dis:read'] }
function providers(snapshot: AuthSnapshot = TENANT) {
  const authValue: AuthContextValue = { profile: null, status: 'authenticated', snapshot, login: () => Promise.resolve(), logout: () => {} }
  return { qc: new QueryClient({ defaultOptions: { queries: { retry: false } } }), authValue }
}
function Wrap({ qc, authValue, entries, children }: { qc: QueryClient; authValue: AuthContextValue; entries: string[]; children: ReactNode }) {
  return (
    <QueryClientProvider client={qc}>
      <AuthContext.Provider value={authValue}>
        <MemoryRouter initialEntries={entries}>{children}</MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>
  )
}

const DETAIL: MappingTemplateDetail = {
  template_id: '0190ac10-5a00-7000-8a00-0000000000a1', source_id: 'manual_csv_upload',
  template_name: 'Daily Sales', template_type: 'sales', ingestion_mode: 'file',
  latest_version: 1, active_version: 1, staged_version: null, draft_version: null,
  versions_count: 1, created_at: '2026-06-06T00:00:00Z', latest_version_created_at: '2026-06-06T00:00:00Z',
  versions: [{
    mapping_version_id: 9001, version: 1, status: 'active',
    mapping_rules: { version: 1, rename: { qty: 'quantity', ts: 'event_date' }, normalize: { event_date: [{ op: 'parse_date', args: {} }] }, cast: { quantity: { type: 'integer' } }, derive: {} },
    field_count: 2, transform_count: 2, predecessor_version_id: null, created_at: '2026-06-06T00:00:00Z',
    created_by_user_id: null, activated_at: '2026-06-06T00:00:00Z', deprecated_at: null,
  }],
}

describe('L3: Mapping Templates detail — Mappings & rules + toggle (real shape)', () => {
  it('renders both cards, rule rows from mapping_rules, and switches Business/Technical', async () => {
    const { qc, authValue } = providers()
    qc.setQueryData(['dis-ui-server', 'mapping-templates', 'detail', TENANT.tenantId, DETAIL.template_id], DETAIL)
    render(<Wrap qc={qc} authValue={authValue} entries={[`/templates/${DETAIL.template_id}`]}>
      <Routes><Route path="/templates/:templateId" element={<TemplateDetail />} /></Routes>
    </Wrap>)
    expect(await screen.findByRole('heading', { name: 'Versions & lifecycle' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Mappings & rules' })).toBeInTheDocument()
    // rule rows from mapping_rules.rename (source fields qty, ts)
    expect(await screen.findByText('qty')).toBeInTheDocument()
    expect(screen.getByText('ts')).toBeInTheDocument()
    // Business view shows the canonical destination somewhere; Technical toggle switches header
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Technical' }))
    expect(await screen.findByRole('columnheader', { name: 'Canonical key' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Business' }))
    expect(await screen.findByRole('columnheader', { name: 'Business label' })).toBeInTheDocument()
  })
})

describe('L3: Dashboard KPI row (real /dashboard/metrics, fixture mode)', () => {
  it('shows Rows ingested + Quality pass rate + pending markers', async () => {
    const { qc, authValue } = providers()
    render(<Wrap qc={qc} authValue={authValue} entries={['/']}><Dashboard /></Wrap>)
    expect(await screen.findByRole('heading', { name: 'Operations Dashboard' })).toBeInTheDocument()
    expect(screen.getByText('Rows ingested')).toBeInTheDocument()
    expect(screen.getByText('Quality pass rate')).toBeInTheDocument()
    // Needs attention is now WIRED to the derived feed (no "not available yet" placeholder).
    const na = screen.getByRole('heading', { name: 'Needs attention' }).closest('.card') as HTMLElement
    expect(within(na).queryByText('Not available yet')).toBeNull()
    expect(within(na).getByRole('link', { name: 'View all' })).toBeInTheDocument()
    // Freshness stays honestly pending (no per-source cadence/SLA data on the backend yet).
    expect(screen.getByText(/pending: no per-source cadence/)).toBeInTheDocument()
  })
})

describe('L3: Data Quality list + detail drawer (fixture mode)', () => {
  it('lists quarantined rows and opens the detail drawer on click', async () => {
    const { qc, authValue } = providers()
    render(<Wrap qc={qc} authValue={authValue} entries={['/data-quality']}><DataQuality /></Wrap>)
    expect(await screen.findByRole('heading', { name: 'Quarantined rows' })).toBeInTheDocument()
    const rows = await screen.findAllByRole('row')
    // click the first data row (index 1; 0 is the header) -> opens the right-side drawer
    await userEvent.setup().click(rows[1])
    // smoke check: the detail is an always-mounted drawer toggling the .on (open) class. The full
    // enriched-detail assertions live in data-quality.test.tsx.
    expect(await screen.findByRole('dialog', { name: 'Quarantine detail' })).toHaveClass('drawer', 'on')
  })
})
