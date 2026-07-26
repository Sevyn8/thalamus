import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { writeToken } from '../../auth/storage'

// Real-mode getStoresOnboardedForTenant (the PLATFORM Square journey's acted-for store read):
// it must hit the cross-tenant endpoint with the acted-for tenant in the path. We mock the mode
// to real and stub global.fetch so the real client runs (mirrors sources.test.ts).

vi.mock('./mode', () => ({
  isRealMode: () => true,
  SERVER_MODE: 'real',
  getBaseUrl: () => '',
}))

import { getStoresOnboardedForTenant } from './stores'

function fakeResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response
}

describe('getStoresOnboardedForTenant (real mode)', () => {
  beforeEach(() => {
    localStorage.clear()
    writeToken('stub-token') // sessionToken() must not throw
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => vi.unstubAllGlobals())

  it('reads the acted-for tenant via the cross-tenant path', async () => {
    vi.mocked(fetch).mockResolvedValue(fakeResponse(200, []))
    await getStoresOnboardedForTenant('ten-zabka')
    expect(fetch).toHaveBeenCalledWith(
      '/api/v1/stores-onboarded/for-tenant/ten-zabka',
      expect.objectContaining({ headers: expect.objectContaining({ authorization: 'Bearer stub-token' }) }),
    )
  })

  it('url-encodes the tenant id', async () => {
    vi.mocked(fetch).mockResolvedValue(fakeResponse(200, []))
    await getStoresOnboardedForTenant('a b/c')
    expect(fetch).toHaveBeenCalledWith('/api/v1/stores-onboarded/for-tenant/a%20b%2Fc', expect.anything())
  })
})
