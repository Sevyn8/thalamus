import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router'

import type { AuthSnapshot } from '../auth/AuthSnapshot'
import { AuthContext } from '../auth/context'
import type { AuthContextValue } from '../auth/context'
import { activeTemplateVersion } from '../lib/dis-ui-server/mapping-templates'
import type {
  MappingTemplate,
  MappingTemplateDetail,
} from '../lib/dis-ui-server/mapping-templates'
import { SourceTemplates } from './SourceTemplates'
import { TemplateDetail } from './TemplateDetail'

// These tests seed the TanStack Query cache (setQueryData) and render — no network, no MSW,
// no fetch mock. They verify the views render the real wire shape; the live fetch itself is
// exercised by the local smoke against dis-ui-server, not in unit tests.

const TENANT: AuthSnapshot = {
  userId: 'u_x',
  tenantId: 't_acme9k2l1mn4',
  storeId: 's_x',
  userType: 'TENANT',
  roles: ['dis:read'],
}

const SUMMARY: MappingTemplate = {
  template_id: '0190ac10-5a00-7000-8a00-0000000000a1',
  source_id: 'manual_csv_upload',
  template_name: 'Daily Sales',
  template_type: 'sales',
  ingestion_mode: 'file',
  latest_version: 2,
  active_version: 1,
  staged_version: null,
  draft_version: 2,
  versions_count: 2,
  created_at: '2026-06-06T00:00:00Z',
  latest_version_created_at: '2026-06-07T00:00:00Z',
}

const DETAIL: MappingTemplateDetail = {
  ...SUMMARY,
  versions: [
    {
      mapping_version_id: 9002,
      version: 2,
      status: 'draft',
      mapping_rules: { version: 1, rename: { qty: 'quantity' }, normalize: {}, cast: {}, derive: {} },
      field_count: 1,
      transform_count: 0,
      predecessor_version_id: 9001,
      created_at: '2026-06-07T00:00:00Z',
      created_by_user_id: null,
      activated_at: null,
      deprecated_at: null,
    },
    {
      mapping_version_id: 9001,
      version: 1,
      status: 'active',
      mapping_rules: { version: 1, rename: { qty: 'quantity' }, normalize: {}, cast: {}, derive: {} },
      field_count: 1,
      transform_count: 0,
      predecessor_version_id: null,
      created_at: '2026-06-06T00:00:00Z',
      created_by_user_id: null,
      activated_at: '2026-06-06T00:00:00Z',
      deprecated_at: null,
    },
  ],
}

function renderSeeded(ui: ReactNode, seed: (qc: QueryClient) => void, initialEntries: string[]) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  seed(qc)
  const authValue: AuthContextValue = {
    profile: null,
    status: 'authenticated',
    snapshot: TENANT,
    login: () => Promise.resolve(),
    logout: () => {},
  }
  return render(
    <QueryClientProvider client={qc}>
      <AuthContext.Provider value={authValue}>
        <MemoryRouter initialEntries={initialEntries}>
          <Routes>
            <Route path="/templates" element={ui} />
            <Route path="/templates/:templateId" element={ui} />
          </Routes>
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
  )
}

describe('SourceTemplates (list)', () => {
  it('renders the live lineage summaries', () => {
    renderSeeded(
      <SourceTemplates />,
      (qc) =>
        qc.setQueryData(['dis-ui-server', 'mapping-templates', TENANT.tenantId, 'all'], [SUMMARY]),
      ['/templates'],
    )
    expect(screen.getByRole('heading', { name: 'Data Ingestion Templates' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Daily Sales' })).toHaveAttribute(
      'href',
      `/templates/${SUMMARY.template_id}`,
    )
    expect(screen.getByText('manual_csv_upload')).toBeInTheDocument()
    expect(screen.getByText('v1')).toBeInTheDocument() // active-version badge
  })
})

describe('TemplateDetail', () => {
  it('renders the version lineage with statuses', () => {
    renderSeeded(
      <TemplateDetail />,
      (qc) =>
        qc.setQueryData(
          ['dis-ui-server', 'mapping-templates', 'detail', TENANT.tenantId, DETAIL.template_id],
          DETAIL,
        ),
      [`/templates/${DETAIL.template_id}`],
    )
    expect(screen.getByRole('heading', { name: 'Daily Sales' })).toBeInTheDocument()
    expect(screen.getByText('active')).toBeInTheDocument()
    expect(screen.getByText('draft')).toBeInTheDocument()
    // Reshaped to the mockup: "Versions & lifecycle" card + "Mappings & rules" card.
    expect(screen.getByRole('heading', { name: 'Versions & lifecycle' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Mappings & rules' })).toBeInTheDocument()
  })
})

describe('activeTemplateVersion', () => {
  it('returns the ACTIVE version row, or null when none', () => {
    // dis-ui semantics: finds the version whose status === 'active' (not by active_version number).
    expect(activeTemplateVersion(DETAIL)?.version).toBe(1)
    const noActive = { ...DETAIL, versions: DETAIL.versions.map((v) => ({ ...v, status: 'draft' as const })) }
    expect(activeTemplateVersion(noActive)).toBeNull()
  })
})
