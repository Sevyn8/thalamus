import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'

import { DisUiServerHttpError } from '../../../lib/dis-ui-server/client'
import { completeCloverOAuth } from '../../../lib/dis-ui-server/clover-oauth'
import { CLOVER_PENDING_KEY } from './config'

// /connectors/clover/launch - the DIVERT-CATCHER (D4), and a real route rather than a
// redirect target of convenience.
//
// Clover can land a browser here in three different shapes, and one of them is not our
// journey at all. If the app is NOT installed on a merchant, Clover's authorize endpoint
// SILENTLY diverts to the App Market listing instead of erroring; the tenant installs from
// there and Clover then launches the app - arriving here with a merchant but no code. The
// same route also catches the MERCHANT-INITIATED case: somebody who discovers Sevyn8 in the
// Clover App Market first and launches it before ever visiting our journey.
//
//   merchant_id + code    consent finished     -> exchange, then the first-pull step
//   merchant_id, no code  installed, not yet   -> resume at Connect, naming the merchant so
//                         authorised              the tenant sees the install worked
//   neither               a direct hit         -> the source catalogue, which is the only
//                                                 coherent thing to show someone with no
//                                                 context
//
// Served inside AuthBoundary so the Bearer is present; App.tsx skipRedirectCallback keeps
// the Auth0 SDK off Clover's ?code/&state.

function messageFor(err: unknown): string {
  // D8: every line says what happened and what to do, in one sentence. No error codes, no
  // first person - a self-serve tenant must never meet oauth_state_tenant_mismatch.
  if (err instanceof DisUiServerHttpError) {
    switch (err.code) {
      case 'oauth_not_configured':
        return 'Clover connections are not available on this environment yet.'
      case 'invalid_oauth_state':
        return 'This Clover connection link has expired. Start the connection again.'
      case 'oauth_state_tenant_mismatch':
        return 'This Clover connection belongs to a different account. Start it again from your own.'
      case 'clover_token_exchange':
        return 'Clover did not complete the connection. Start it again.'
      default:
        return 'The Clover connection did not finish. Start it again.'
    }
  }
  return 'The Clover connection did not finish. Start it again.'
}

export function CloverLaunch() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const [exchangeError, setExchangeError] = useState<string | null>(null)
  // Run the exchange at most once (guards React StrictMode's double-invoke: the code is
  // single-use at Clover, so a second POST would fail).
  const started = useRef(false)

  const merchantId = params.get('merchant_id')
  const code = params.get('code')
  const state = params.get('state')

  useEffect(() => {
    // Branch 3: neither - a direct hit with no context. The source catalogue is the only
    // coherent destination.
    if (merchantId === null && code === null) {
      navigate('/connect', { replace: true })
      return
    }
    // Branch 2: installed but not authorised. Resume at Connect, naming the merchant.
    if (code === null || state === null) {
      const merchant = merchantId === null ? '' : `&merchant_id=${encodeURIComponent(merchantId)}`
      navigate(`/connect/clover?step=connect${merchant}`, { replace: true })
      return
    }
    // Branch 1: consent finished. Exchange, then the first-pull step.
    if (started.current) return
    started.current = true
    let active = true
    completeCloverOAuth({ code, state, merchant_id: merchantId ?? '' })
      .then((result) => {
        if (!active) return
        sessionStorage.removeItem(CLOVER_PENDING_KEY)
        navigate(
          `/connect/clover?connected=1&source_id=${encodeURIComponent(
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
  }, [merchantId, code, state, navigate])

  if (exchangeError !== null) {
    return (
      <section className="mx-auto mt-10 max-w-md px-4">
        <h1 className="mb-2 text-lg font-semibold">Clover connection</h1>
        <p role="alert" className="mb-4 text-sm text-red-600">
          {exchangeError}
        </p>
        <button type="button" className="btn pri" onClick={() => navigate('/connect/clover')}>
          Back to Clover setup
        </button>
      </section>
    )
  }

  return (
    <section className="mx-auto mt-10 max-w-md px-4">
      <p className="text-sm text-gray-500">Finishing the Clover connection...</p>
    </section>
  )
}
