import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { writeToken } from '../../auth/storage'

// Real-mode square-oauth client: mock the mode to real + stub global.fetch so the REAL client
// runs (mirrors sources.test.ts). Verifies the exact S2 wire paths and the typed-error surface.

vi.mock('./mode', () => ({
  isRealMode: () => true,
  SERVER_MODE: 'real',
  getBaseUrl: () => '',
}))

import { completeSquareOAuth, getSquareAuthorizeUrl } from './square-oauth'

function fakeResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response
}

describe('square-oauth client (real mode)', () => {
  beforeEach(() => {
    localStorage.clear()
    writeToken('stub-token') // sessionToken() must not throw
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => vi.unstubAllGlobals())

  it('GETs the authorize-url with the source_id query and returns {authorize_url, state}', async () => {
    vi.mocked(fetch).mockResolvedValue(
      fakeResponse(200, { authorize_url: 'https://connect.squareupsandbox.com/oauth2/authorize?x', state: 'st' }),
    )
    const result = await getSquareAuthorizeUrl('square_pos_v2')
    expect(fetch).toHaveBeenCalledWith(
      '/api/v1/connectors/square/oauth/authorize-url?source_id=square_pos_v2',
      expect.objectContaining({ headers: expect.objectContaining({ authorization: 'Bearer stub-token' }) }),
    )
    expect(result.state).toBe('st')
    expect(result.authorize_url).toContain('/oauth2/authorize')
  })

  it('POSTs code+state to /complete and returns the connected result', async () => {
    vi.mocked(fetch).mockResolvedValue(
      fakeResponse(200, { connector: 'square', status: 'connected', source_id: 'square_pos_v2', merchant_id: 'M1' }),
    )
    const result = await completeSquareOAuth({ code: 'c', state: 's' })
    expect(fetch).toHaveBeenCalledWith(
      '/api/v1/connectors/square/oauth/complete',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ code: 'c', state: 's' }) }),
    )
    expect(result).toMatchObject({ status: 'connected', merchant_id: 'M1' })
  })

  it('surfaces a typed 4xx from /complete (DisUiServerHttpError with code)', async () => {
    vi.mocked(fetch).mockResolvedValue(
      fakeResponse(502, { error: { code: 'square_token_exchange', message: 'boom', details: {} } }),
    )
    await expect(completeSquareOAuth({ code: 'bad', state: 's' })).rejects.toMatchObject({
      status: 502,
      code: 'square_token_exchange',
    })
  })
})
