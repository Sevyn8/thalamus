import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import { vi } from 'vitest'

import type { AuthSnapshot } from '../auth/AuthSnapshot'
import { DisUiServerHttpError } from '../lib/dis-ui-server/client'
import { renderWithProviders } from '../test/renderWithProviders'
import { TemplateDetail } from './TemplateDetail'

// Inline template rename (Finding 4): backend already supports PATCH template_name; these tests
// cover the new UI surface. mapping-templates is mocked so patchMappingTemplate + useMappingTemplate
// are controllable (activeTemplateVersion stays real); client is NOT mocked, so the 409 case throws
// the real DisUiServerHttpError the component's `instanceof` check relies on.

// vi.mock factories hoist above module consts, so DETAIL + refetch live in a hoisted block.
const { DETAIL, refetch } = vi.hoisted(() => ({
  DETAIL: {
    template_id: '0190ac10-5a00-7000-8a00-0000000000a1',
    source_id: 'square_pos_v2',
    template_name: 'square snapshot',
    template_type: 'snapshot',
    ingestion_mode: 'api',
    latest_version: 1,
    active_version: 1,
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
  },
  refetch: vi.fn(),
}))

vi.mock('../lib/dis-ui-server/mapping-templates', async (importActual) => {
  const actual = await importActual<typeof import('../lib/dis-ui-server/mapping-templates')>()
  return {
    ...actual,
    useMappingTemplate: vi.fn(() => ({
      data: DETAIL,
      isPending: false,
      isError: false,
      error: null,
      refetch,
    })),
    patchMappingTemplate: vi.fn().mockResolvedValue(DETAIL),
  }
})
vi.mock('../lib/dis-ui-server/mapping-fields', () => ({
  useTemplateMappingFieldsForType: vi.fn(() => ({ data: [] })),
}))
// The source lookup supplies both the upload-guard channel and the PLATFORM acted-for tenant_id.
vi.mock('../lib/dis-ui-server/sources', () => ({
  useSources: vi.fn(() => ({
    data: [{ tenant_id: 'ten-owner', source_id: 'square_pos_v2', channel: 'api' }],
  })),
}))

import { patchMappingTemplate } from '../lib/dis-ui-server/mapping-templates'

const TENANT: AuthSnapshot = {
  userId: 'u',
  tenantId: 'ten-owner',
  storeId: null,
  userType: 'TENANT',
  roles: ['dis:write'],
}
const PLATFORM: AuthSnapshot = {
  userId: 'ops',
  tenantId: null,
  storeId: null,
  userType: 'PLATFORM',
  roles: ['dis:ops'],
}

function renderDetail(snapshot: AuthSnapshot): void {
  renderWithProviders(
    <Routes>
      <Route path="/templates/:templateId" element={<TemplateDetail />} />
    </Routes>,
    { snapshot, initialEntries: [`/templates/${DETAIL.template_id}`] },
  )
}

describe('TemplateDetail rename', () => {
  beforeEach(() => vi.clearAllMocks())

  it('TENANT: renames via PATCH with NO acted-for tenant, then refetches', async () => {
    renderDetail(TENANT)
    fireEvent.click(screen.getByRole('button', { name: 'Rename template' }))
    fireEvent.change(screen.getByLabelText('Template name'), { target: { value: 'square v2' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(patchMappingTemplate).toHaveBeenCalledWith(DETAIL.template_id, {
        template_name: 'square v2',
        acting_for_tenant_id: undefined,
      }),
    )
    await waitFor(() => expect(refetch).toHaveBeenCalled())
  })

  it('PLATFORM: threads the acted-for tenant (derived from the source) into PATCH', async () => {
    renderDetail(PLATFORM)
    fireEvent.click(screen.getByRole('button', { name: 'Rename template' }))
    fireEvent.change(screen.getByLabelText('Template name'), { target: { value: 'square v2' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(patchMappingTemplate).toHaveBeenCalledWith(DETAIL.template_id, {
        template_name: 'square v2',
        acting_for_tenant_id: 'ten-owner',
      }),
    )
  })

  it('renders a 409 (name already used) inline and does not refetch', async () => {
    vi.mocked(patchMappingTemplate).mockRejectedValueOnce(
      new DisUiServerHttpError(
        409,
        'mapping_template_name_conflict',
        'name already used by another template of this source',
        {},
      ),
    )
    renderDetail(TENANT)
    fireEvent.click(screen.getByRole('button', { name: 'Rename template' }))
    fireEvent.change(screen.getByLabelText('Template name'), { target: { value: 'dup name' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/already used/i)
    expect(refetch).not.toHaveBeenCalled()
  })
})
