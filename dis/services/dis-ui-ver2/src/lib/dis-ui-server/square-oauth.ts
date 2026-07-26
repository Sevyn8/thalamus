import { getJson, postJson } from './client'
import { isRealMode } from './mode'

// The Square OAuth connect seam (S2 endpoints). Shaped EXACTLY to the real dis-ui-server
// handlers (services/dis-ui-server/.../handlers/connectors_square.py):
//   - GET  /api/v1/connectors/square/oauth/authorize-url?source_id=... -> {authorize_url, state}
//   - POST /api/v1/connectors/square/oauth/complete {code, state}
//       -> {connector, status, source_id, merchant_id} | typed 4xx (DisUiServerHttpError)
// The tenant is derived server-side from the Bearer token (never a param). Mode-aware: real
// mode calls the live endpoints; fixture mode returns a local stub so the journey walks
// offline (the stub authorize URL lands straight back on the callback with a fixture code).

export type SquareAuthorizeUrl = {
  authorize_url: string
  state: string
}

export type SquareOAuthResult = {
  connector: string
  status: string
  source_id: string
  merchant_id: string
}

export async function getSquareAuthorizeUrl(sourceId: string): Promise<SquareAuthorizeUrl> {
  if (isRealMode()) {
    return getJson<SquareAuthorizeUrl>(
      `/api/v1/connectors/square/oauth/authorize-url?source_id=${encodeURIComponent(sourceId)}`,
    )
  }
  // Fixture: a same-origin stub authorize URL that redirects straight back to the callback,
  // so the offline journey can be walked with no Square account and no backend.
  const state = `fixture-state-${sourceId}`
  const authorizeUrl = `${window.location.origin}/connectors/square/callback?code=fixture-code&state=${encodeURIComponent(
    state,
  )}`
  return Promise.resolve({ authorize_url: authorizeUrl, state })
}

export async function completeSquareOAuth(body: {
  code: string
  state: string
}): Promise<SquareOAuthResult> {
  if (isRealMode()) {
    return postJson<SquareOAuthResult>('/api/v1/connectors/square/oauth/complete', body)
  }
  return Promise.resolve({
    connector: 'square',
    status: 'connected',
    source_id: 'square_pos_v2',
    merchant_id: 'FIXTURE_MERCHANT',
  })
}
