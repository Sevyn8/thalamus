import { Auth0Provider } from '@auth0/auth0-react'
import type { AppState } from '@auth0/auth0-react'
import { QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { BrowserRouter, useNavigate } from 'react-router'

import { Auth0AuthProvider } from './auth/Auth0AuthProvider'
import { renderFixtureApp } from '@devAuthSeam'
import { isRealMode } from './lib/dis-ui-server/mode'
import { queryClient } from './lib/queryClient'
import { AppRoutes } from './routes/AppRoutes'

// Auth mode split (mirrors the backend STUB|AUTH0). Real mode wraps the tree in the Auth0
// SDK provider + the Auth0->AuthContextValue adapter. Fixture mode is reachable ONLY through
// '@devAuthSeam', which vite.config.ts resolves at BUILD time: the dev variant returns the
// persona-picker tree, the production variant returns null and imports no fixture code at all.
// A production artifact therefore contains no path to it, rather than a path it declines to
// take. isRealMode() reads VITE_DIS_UI_SERVER_MODE, inlined by Vite at build.

// Auth0Provider needs useNavigate for onRedirectCallback, so it lives INSIDE
// BrowserRouter via this wrapper (the idiomatic @auth0/auth0-react + react-router
// pattern). Config comes from the build-time VITE_AUTH0_* vars; the SPA is a public
// PKCE client (no secret). redirect_uri points at the public /callback route.
function Auth0ProviderWithNavigate({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
  return (
    <Auth0Provider
      domain={import.meta.env.VITE_AUTH0_DOMAIN}
      clientId={import.meta.env.VITE_AUTH0_CLIENT_ID}
      useRefreshTokens={true}
      cacheLocation="localstorage"
      authorizationParams={{
        audience: import.meta.env.VITE_AUTH0_AUDIENCE,
        scope: 'openid profile email offline_access',
        redirect_uri: `${window.location.origin}/callback`,
      }}
      onRedirectCallback={(appState?: AppState) => {
        navigate(appState?.returnTo ?? '/', { replace: true })
      }}
      // Vendor OAuth callbacks carry the VENDOR's own ?code&state. Without this, the Auth0
      // SDK would try to process them as an Auth0 login response and error. Skip the SDK's
      // redirect handling on exactly those paths so each vendor's route owns its exchange.
      // Clover has two: the dashboard-registered callback and the launch divert-catcher,
      // which Clover can also hit directly on a merchant-initiated App Market launch.
      skipRedirectCallback={VENDOR_OAUTH_PATHS.has(window.location.pathname)}
    >
      {children}
    </Auth0Provider>
  )
}

// Paths where a VENDOR owns the ?code&state, not Auth0.
const VENDOR_OAUTH_PATHS = new Set([
  '/connectors/square/callback',
  '/connectors/clover/callback',
  '/connectors/clover/launch',
])

function RealModeApp() {
  return (
    <BrowserRouter>
      <Auth0ProviderWithNavigate>
        <Auth0AuthProvider>
          <AppRoutes />
        </Auth0AuthProvider>
      </Auth0ProviderWithNavigate>
    </BrowserRouter>
  )
}

function App() {
  // `?? <RealModeApp />` is the fail-closed half. In a production build renderFixtureApp
  // always returns null, so ANY mode string - 'real', missing, or misspelled - lands on the
  // Auth0 tree. Fixture mode cannot be reached by getting a build variable wrong.
  const fixture = isRealMode()
    ? null
    : renderFixtureApp(
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>,
      )

  return (
    <QueryClientProvider client={queryClient}>{fixture ?? <RealModeApp />}</QueryClientProvider>
  )
}

export default App
