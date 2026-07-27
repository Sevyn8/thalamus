import { Navigate, useSearchParams } from 'react-router'

// /connectors/clover/callback - the redirect URI registered in the Clover dashboard.
//
// IT FORWARDS TO /connectors/clover/launch AND EXCHANGES NOTHING ITSELF. That is deliberate:
// ONE STATE MACHINE, ONE PLACE TO CHANGE. Launch already owns the three-way branch (consent
// finished / installed-but-not-authorised / direct hit) because Clover can arrive there
// without ever passing through here - a merchant-initiated App Market launch does exactly
// that. Handling the exchange here as well would mean two implementations of the same
// branch, and the single-use authorization code would have two places able to spend it.
// DO NOT "simplify" this by moving the exchange back in; the duplication is the bug it
// prevents.
//
// The two paths stay separate rather than registering /launch with Clover directly because
// they answer to different owners: this is the address given to the Clover dashboard and
// must not change once registered, while launch is ours to reshape as the branch grows.
//
// THE FORWARD IS A REPLACE, NOT A PUSH, and that is load-bearing. A push would leave
// /callback?code=X in history; the back button would return to it, forward again, and
// re-exchange a SPENT code. The useRef guard in launch only holds within one mount, so a
// remount defeats it. Replace means neither this URL nor launch's survives: launch also
// replaces on success, so after a completed exchange the history holds only
// /connect/clover?connected=1 and a refresh or restored tab cannot re-fire the code. This
// matches SquareCallback, which clears its code the same way.

export function CloverCallback() {
  const [params] = useSearchParams()
  const query = params.toString()
  return <Navigate to={`/connectors/clover/launch${query === '' ? '' : `?${query}`}`} replace />
}
