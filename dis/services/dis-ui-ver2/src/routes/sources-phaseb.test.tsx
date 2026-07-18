import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router'

import type { AuthSnapshot } from '../auth/AuthSnapshot'
import { AuthContext } from '../auth/context'
import type { AuthContextValue } from '../auth/context'
import type { MappingTemplateDetail } from '../lib/dis-ui-server/mapping-templates'
import type { ChannelWire, SourceRow } from '../lib/dis-ui-server/sources'
import { Sources } from './Sources'
import { TemplateDetail } from './TemplateDetail'

// Phase B (D112): the Upload guard now derives from the source CHANNEL (GET /sources), not the
// wire-defaulted ingestion_mode — hide Upload ONLY for api/reverse_api; allow for
// file/csv/erp/NULL/missing (no regression). Plus the Data Pipelines Method column from the real
// channel. Fixture-mode renders with the query caches seeded to control the channel.

const TENANT: AuthSnapshot = { userId: 'u', tenantId: 't_acme9k2l1mn4', storeId: 's', userType: 'TENANT', roles: ['dis:read'] }

function providers() {
  const authValue: AuthContextValue = {
    status: 'authenticated',
    snapshot: TENANT,
    login: () => Promise.resolve(),
    logout: () => {},
  }
  return { qc: new QueryClient({ defaultOptions: { queries: { retry: false } } }), authValue }
}

function Wrap({
  qc,
  authValue,
  children,
}: {
  qc: QueryClient
  authValue: AuthContextValue
  children: ReactNode
}) {
  return (
    <QueryClientProvider client={qc}>
      <AuthContext.Provider value={authValue}>{children}</AuthContext.Provider>
    </QueryClientProvider>
  )
}

function detail(sourceId: string): MappingTemplateDetail {
  return {
    template_id: '0190ac10-5a00-7000-8a00-0000000000a1',
    source_id: sourceId,
    template_name: 'Daily Sales',
    template_type: 'sales',
    ingestion_mode: 'file',
    latest_version: 1,
    active_version: 1, // active present -> Upload shows unless the channel is push/pull
    staged_version: null,
    draft_version: null,
    versions_count: 1,
    created_at: '2026-06-06T00:00:00Z',
    latest_version_created_at: '2026-06-06T00:00:00Z',
    versions: [
      {
        mapping_version_id: 9001,
        version: 1,
        status: 'active',
        mapping_rules: { version: 1, rename: {}, normalize: {}, cast: {}, derive: {} },
        field_count: 0,
        transform_count: 0,
        predecessor_version_id: null,
        created_at: '2026-06-06T00:00:00Z',
        created_by_user_id: null,
        activated_at: '2026-06-06T00:00:00Z',
        deprecated_at: null,
      },
    ],
  }
}

function sourceRow(source_id: string, channel: ChannelWire | null): SourceRow {
  return {
    tenant_id: '0190ac10-1a01-7001-8a01-0000000000a1',
    source_id,
    display_name: source_id,
    channel,
    store_id: null,
    schedule: null,
    status: 'active',
    created_at: '2026-06-06T00:00:00Z',
    updated_at: '2026-06-06T00:00:00Z',
  }
}

async function renderGuard(sourceChannel: ChannelWire | null | 'MISSING'): Promise<void> {
  const { qc, authValue } = providers()
  const d = detail('acme_source')
  qc.setQueryData(['dis-ui-server', 'mapping-templates', 'detail', TENANT.tenantId, d.template_id], d)
  // Seed GET /sources: either the source with a channel, or an empty list (MISSING).
  const sources = sourceChannel === 'MISSING' ? [] : [sourceRow('acme_source', sourceChannel)]
  qc.setQueryData(['dis-ui-server', 'sources', TENANT.tenantId], sources)
  render(
    <Wrap qc={qc} authValue={authValue}>
      <MemoryRouter initialEntries={[`/templates/${d.template_id}`]}>
        <Routes>
          <Route path="/templates/:templateId" element={<TemplateDetail />} />
        </Routes>
      </MemoryRouter>
    </Wrap>,
  )
  await screen.findByRole('heading', { name: 'Daily Sales' })
}

describe('Upload guard from source channel (D112 Phase B)', () => {
  it('HIDES Upload for an api source', async () => {
    await renderGuard('api')
    expect(screen.queryByRole('link', { name: 'Upload data' })).not.toBeInTheDocument()
  })

  it('HIDES Upload for a reverse_api source', async () => {
    await renderGuard('reverse_api')
    expect(screen.queryByRole('link', { name: 'Upload data' })).not.toBeInTheDocument()
  })

  it('SHOWS Upload for a csv_upload source', async () => {
    await renderGuard('csv_upload')
    expect(screen.getByRole('link', { name: 'Upload data' })).toBeInTheDocument()
  })

  it('SHOWS Upload for a NULL-channel source (un-inferred — no regression)', async () => {
    await renderGuard(null)
    expect(screen.getByRole('link', { name: 'Upload data' })).toBeInTheDocument()
  })

  it('SHOWS Upload when the source is missing from /sources (no regression)', async () => {
    await renderGuard('MISSING')
    expect(screen.getByRole('link', { name: 'Upload data' })).toBeInTheDocument()
  })
})

describe('Data Pipelines Method column from real channel (D112 Phase B)', () => {
  it('renders Method from the source channel, "—" for NULL', async () => {
    const { qc, authValue } = providers()
    render(
      <Wrap qc={qc} authValue={authValue}>
        <MemoryRouter initialEntries={['/pipelines']}>
          <Sources />
        </MemoryRouter>
      </Wrap>,
    )
    expect(await screen.findByRole('heading', { name: 'Data Sources' })).toBeInTheDocument()
    expect(await screen.findByRole('columnheader', { name: 'Method' })).toBeInTheDocument()
    // fixture: manual_csv_upload -> Manual CSV, shopify_pos_v2 -> API, legacy_feed -> null -> —
    expect(screen.getByText('Manual CSV')).toBeInTheDocument()
    expect(screen.getByText('API')).toBeInTheDocument()
    expect(screen.getByText('legacy_feed')).toBeInTheDocument()
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
  })
})
