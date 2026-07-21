import { useAuth0 } from '@auth0/auth0-react'

// The Auth0 redirect target (redirect_uri = <origin>/callback). @auth0/auth0-react
// processes the ?code&state on load and then fires onRedirectCallback (App.tsx),
// which navigates to the intended route, so this typically renders only for a
// moment. A public route (like /dev/login), outside AuthBoundary.
export function Callback() {
  const { error } = useAuth0()
  if (error) {
    return (
      <section className="mx-auto mt-16 max-w-md px-4">
        <p role="alert" className="text-sm text-red-600">
          Sign-in failed: {error.message}
        </p>
      </section>
    )
  }
  return (
    <section className="mx-auto mt-16 max-w-md px-4">
      <p className="text-sm text-gray-500">Signing in...</p>
    </section>
  )
}
