// The shape both dev-auth seam variants implement. Imports NOTHING from src/auth/dev,
// so this file is safe in either module graph.
//
// The seam exists because a runtime branch cannot remove code from a bundle. Vite resolves
// '@devAuthSeam' to devAuthSeam.dev.tsx or devAuthSeam.prod.tsx at BUILD time (see
// vite.config.ts), so the production graph has no path to the fixture provider, the persona
// list, the stub signer or the published HS256 constant.

import type { ReactElement, ReactNode } from 'react'

/** Shape of one fixture tenant row; mirrors TenantSelf without importing it. */
export type TenantSelfFixture = {
  tenant_id: string
  name: string | null
  display_code: string | null
}

export type DevAuthSeam = {
  /** The fixture (persona-picker) auth tree, or null when this build has no fixture auth. */
  renderFixtureApp: (children: ReactNode) => ReactElement | null
  /** Dev-only <Route> elements spliced into the shared registry. Empty in production. */
  devRoutes: ReactElement[]
  /**
   * Where AuthBoundary sends an unauthenticated caller. '/signin' in production (the Auth0
   * redirect); '/dev/login' in dev builds, so logging out locally returns to the persona
   * picker instead of a sign-in page the fixture provider cannot satisfy.
   */
  signInPath: string
  /**
   * Fixture tenant rows keyed by tenant_id, resolving the dev persona's own tenant offline.
   * Empty in production: the row exists only to match the persona, so it carries the seeded
   * tenant UUID and belongs on the dev side of the boundary with the persona itself.
   */
  tenantSelfFixtures: Record<string, TenantSelfFixture>
}
