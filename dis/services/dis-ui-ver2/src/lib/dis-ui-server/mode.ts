export type ServerMode = 'fixture' | 'real'

// Runtime switch between fixture mode (default, no backend) and real mode (calls
// dis-ui-server). Anything other than 'real' resolves to 'fixture', so the app
// runs locally with no env configured.
export const SERVER_MODE: ServerMode =
  import.meta.env.VITE_DIS_UI_SERVER_MODE === 'real' ? 'real' : 'fixture'

// Lazy mode read: reads VITE_DIS_UI_SERVER_MODE at CALL time, unlike the load-time
// SERVER_MODE const. Vite still inlines it at build (the deployed value is fixed per
// the image build), but reading lazily lets tests flip the mode per-case via
// vi.stubEnv (the const is frozen at import). The real-wired modules branch on this;
// the fixture-only modules keep using SERVER_MODE for their ensureFixtureMode guard.
export function isRealMode(): boolean {
  return import.meta.env.VITE_DIS_UI_SERVER_MODE === 'real'
}

export function getBaseUrl(): string {
  // The browser calls same-origin "/api/v1/..."; nginx (prod) or the Vite dev proxy
  // (dev) forwards to dis-ui-server, so there is no baked URL and no CORS. Default is
  // '' (relative). A missing backend URL is caught loudly at the nginx layer (container
  // start guard), not here. An explicit absolute VITE_DIS_UI_SERVER_BASE_URL still works
  // for direct-to-backend local dev.
  return import.meta.env.VITE_DIS_UI_SERVER_BASE_URL ?? ''
}
