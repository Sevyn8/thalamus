import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { writeToken } from '../../auth/storage'

// Real-mode createMappingTemplateIfAbsent (the Square Register step's template write): a 409 is
// TOLERATED (template_name already used by a prior run's template of this source), any other error
// propagates. We mock the mode to real and stub global.fetch so the REAL client runs (constructing
// the real DisUiServerHttpError that the `instanceof` check relies on) — mirrors sources.test.ts.

vi.mock('./mode', () => ({
  isRealMode: () => true,
  SERVER_MODE: 'real',
  getBaseUrl: () => '',
}))

import type { MappingTemplateCreate } from './mapping-templates'
import { createMappingTemplateIfAbsent } from './mapping-templates'

const BODY: MappingTemplateCreate = {
  source_id: 'square_pos_v2',
  template_name: 'square snapshot',
  template_type: 'snapshot',
  columns: [{ src_key: 'sku_id', dest_key: 'sku_id' }],
}

function fakeResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response
}

describe('createMappingTemplateIfAbsent (real mode, 409-tolerant)', () => {
  beforeEach(() => {
    localStorage.clear()
    writeToken('stub-token') // sessionToken() must not throw
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => vi.unstubAllGlobals())

  it('returns true when the template is newly created (201)', async () => {
    vi.mocked(fetch).mockResolvedValue(fakeResponse(201, { template_id: 'tmpl_1' }))
    await expect(createMappingTemplateIfAbsent(BODY)).resolves.toBe(true)
    expect(fetch).toHaveBeenCalledWith(
      '/api/v1/mapping-templates',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('returns false on a 409 (name already used — tolerated, not thrown)', async () => {
    vi.mocked(fetch).mockResolvedValue(
      fakeResponse(409, {
        error: { code: 'mapping_template_name_conflict', message: 'dup', details: {} },
      }),
    )
    await expect(createMappingTemplateIfAbsent(BODY)).resolves.toBe(false)
  })

  it('re-throws any non-409 error (never silently swallowed)', async () => {
    vi.mocked(fetch).mockResolvedValue(
      fakeResponse(400, { error: { code: 'invalid_mapping', message: 'boom', details: {} } }),
    )
    await expect(createMappingTemplateIfAbsent(BODY)).rejects.toMatchObject({ status: 400 })
  })
})
