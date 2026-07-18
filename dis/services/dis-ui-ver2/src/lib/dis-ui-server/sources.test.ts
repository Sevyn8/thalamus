import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { writeToken } from '../../auth/storage'

// Real-mode createSourceIfAbsent (the Connect wizard's source-first write): a 409 is TOLERATED
// (source already exists — prior run / backfill), any other error propagates. We mock the mode to
// real and stub global.fetch, so the REAL client runs (constructing the real DisUiServerHttpError
// that createSourceIfAbsent's `instanceof` check relies on) — no client module mock, no dual-class.

vi.mock('./mode', () => ({
  isRealMode: () => true,
  SERVER_MODE: 'real',
  getBaseUrl: () => '',
}))

import { createSourceIfAbsent } from './sources'

const BODY = { source_id: 'sq', display_name: 'Square', channel: 'csv_upload' as const }

function fakeResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response
}

describe('createSourceIfAbsent (real mode, 409-tolerant)', () => {
  beforeEach(() => {
    localStorage.clear()
    writeToken('stub-token') // sessionToken() must not throw
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => vi.unstubAllGlobals())

  it('returns true when the source is newly created (201)', async () => {
    vi.mocked(fetch).mockResolvedValue(fakeResponse(201, { source_id: 'sq' }))
    await expect(createSourceIfAbsent(BODY)).resolves.toBe(true)
    expect(fetch).toHaveBeenCalledWith('/api/v1/sources', expect.objectContaining({ method: 'POST' }))
  })

  it('returns false on a 409 (already exists — tolerated, not thrown)', async () => {
    vi.mocked(fetch).mockResolvedValue(
      fakeResponse(409, { error: { code: 'source_already_exists', message: 'dup', details: {} } }),
    )
    await expect(createSourceIfAbsent(BODY)).resolves.toBe(false)
  })

  it('re-throws any non-409 error (never silently swallowed)', async () => {
    vi.mocked(fetch).mockResolvedValue(
      fakeResponse(500, { error: { code: 'internal', message: 'boom', details: {} } }),
    )
    await expect(createSourceIfAbsent(BODY)).rejects.toMatchObject({ status: 500 })
  })
})
