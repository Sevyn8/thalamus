import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'

import { DisUiServerHttpError } from '../../../lib/dis-ui-server/client'
import { completeSquareOAuth } from '../../../lib/dis-ui-server/square-oauth'
import { SQUARE_PENDING_KEY } from './config'

// The Square OAuth callback, served at EXACTLY /connectors/square/callback (the URL registered
// in the Square dashboard; nginx SPA fallback routes the deep link to index.html). Inside
// AuthBoundary, so the Bearer token is present and an expired-mid-consent session is bounced to
// login by the boundary (re-authorize on return; nothing is half-done as the vault is written
// only on a successful complete). App.tsx sets skipRedirectCallback for this exact path so the
// Auth0 SDK does not try to process Square's ?code/&state as an Auth0 login response.
//
// Reads code + state, POSTs /complete, and on success routes into the journey's first-pull step.
// Failures render the typed S2 error (mapped to a friendly line) with a retry back to the journey.

function messageFor(err: unknown): string {
  if (err instanceof DisUiServerHttpError) {
    switch (err.code) {
      case 'oauth_not_configured':
        return 'Square OAuth is not configured on this server.'
      case 'invalid_oauth_state':
        return 'This Square connection link is invalid or has expired. Start the connection again.'
      case 'oauth_state_tenant_mismatch':
        return 'This Square connection does not belong to your account.'
      case 'square_token_exchange':
        return 'Square could not complete the connection. Please try again.'
      default:
        return err.message
    }
  }
  return err instanceof Error ? err.message : 'The Square connection failed.'
}

export function SquareCallback() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  // Only the async exchange failure needs state; the pre-validation errors below are derived at
  // render time, so the effect never calls setState synchronously.
  const [exchangeError, setExchangeError] = useState<string | null>(null)
  // Run the exchange at most once (guards React StrictMode's double-invoke: the code is
  // single-use at Square, so a second POST would fail).
  const started = useRef(false)

  const code = params.get('code')
  const state = params.get('state')
  const declined = params.get('error') // Square sends ?error=access_denied when the seller declines

  // Derived at render: a declined consent or a missing code needs no network call.
  const preError =
    declined !== null
      ? 'Square authorization was declined.'
      : code === null || state === null
        ? 'The Square response was missing its authorization code.'
        : null

  useEffect(() => {
    if (started.current || declined !== null || code === null || state === null) return
    started.current = true
    let active = true
    completeSquareOAuth({ code, state })
      .then((result) => {
        if (!active) return
        sessionStorage.removeItem(SQUARE_PENDING_KEY)
        navigate(
          `/connect/square?connected=1&source_id=${encodeURIComponent(
            result.source_id,
          )}&merchant_id=${encodeURIComponent(result.merchant_id)}`,
          { replace: true },
        )
      })
      .catch((err: unknown) => {
        if (!active) return
        setExchangeError(messageFor(err))
      })
    return () => {
      active = false
    }
  }, [code, state, declined, navigate])

  const error = preError ?? exchangeError

  if (error !== null) {
    return (
      <section className="mx-auto mt-10 max-w-md px-4">
        <h1 className="mb-2 text-lg font-semibold">Square connection</h1>
        <p role="alert" className="mb-4 text-sm text-red-600">
          {error}
        </p>
        <button type="button" className="btn pri" onClick={() => navigate('/connect/square')}>
          Back to Square setup
        </button>
      </section>
    )
  }

  return (
    <section className="mx-auto mt-10 max-w-md px-4">
      <p className="text-sm text-gray-500">Finishing the Square connection...</p>
    </section>
  )
}
