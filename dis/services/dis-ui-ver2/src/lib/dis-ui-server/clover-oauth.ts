import { getJson, postJson } from './client'
import { isRealMode } from './mode'

// The Clover OAuth connect seam. Shaped EXACTLY to the real dis-ui-server handlers
// (services/dis-ui-server/.../handlers/connectors_clover.py):
//   - GET  /api/v1/connectors/clover/oauth/authorize-url?source_id=... -> {authorize_url, state}
//   - POST /api/v1/connectors/clover/oauth/complete {code, state, merchant_id}
//       -> {connector, status, source_id, merchant_id} | typed 4xx (DisUiServerHttpError)
//
// DUPLICATED from square-oauth.ts rather than generalised, deliberately (D5). Square and
// Clover OAuth genuinely differ - Clover's complete carries a merchant_id the SPA read off
// the callback, because Clover's token response does not contain one - and a shared
// /connectors/{vendor}/... abstraction would hide that. Two implementations is data; three
// is when to extract.
//
// The tenant is derived server-side from the Bearer token (never a param). Mode-aware: real
// mode calls the live endpoints; fixture mode returns a local stub so the journey walks
// offline with no Clover account and no backend.

export type CloverAuthorizeUrl = {
  authorize_url: string
  state: string
}

export type CloverOAuthResult = {
  connector: string
  status: string
  source_id: string
  merchant_id: string
}

// actingForTenantId is the PLATFORM impersonation target. Self-serve TENANT is the primary
// path and passes undefined (the server pins its token tenant; naming one would be a 403).
export async function getCloverAuthorizeUrl(
  sourceId: string,
  actingForTenantId?: string,
): Promise<CloverAuthorizeUrl> {
  if (isRealMode()) {
    const acted =
      actingForTenantId === undefined
        ? ''
        : `&acting_for_tenant_id=${encodeURIComponent(actingForTenantId)}`
    return getJson<CloverAuthorizeUrl>(
      `/api/v1/connectors/clover/oauth/authorize-url?source_id=${encodeURIComponent(sourceId)}${acted}`,
    )
  }
  // Fixture: a same-origin stub authorize URL that redirects straight back to the launch
  // route with the shape Clover really sends (merchant_id + code + state), so the offline
  // journey exercises the divert-catcher's happy branch.
  const state = `fixture-state-${sourceId}`
  const authorizeUrl =
    `${window.location.origin}/connectors/clover/launch` +
    `?merchant_id=FIXTUREMERCHANT&employee_id=FIXTUREEMPLOYEE&code=fixture-code` +
    `&state=${encodeURIComponent(state)}`
  return Promise.resolve({ authorize_url: authorizeUrl, state })
}

export async function completeCloverOAuth(body: {
  code: string
  state: string
  merchant_id: string
}): Promise<CloverOAuthResult> {
  if (isRealMode()) {
    return postJson<CloverOAuthResult>('/api/v1/connectors/clover/oauth/complete', body)
  }
  return Promise.resolve({
    connector: 'clover',
    status: 'connected',
    source_id: 'clover_pos_v1',
    merchant_id: body.merchant_id,
  })
}
