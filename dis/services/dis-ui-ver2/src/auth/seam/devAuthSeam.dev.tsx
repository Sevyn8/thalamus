// DEVELOPMENT/TEST variant of the dev-auth seam. Selected by vite.config.ts for
// `vite dev`, vitest, and any build that is not a deployable production build.
//
// This is the ONLY module in the tree that may reach src/auth/dev/**. Everything
// fixture-mode hangs off these two exports, so "is the stub in this build?" has one
// answer: which seam file the alias resolved to.

import { Route } from 'react-router'
import type { ReactElement, ReactNode } from 'react'

import { AuthProvider } from '../AuthProvider'
import { DevLogin } from '../../routes/DevLogin'
import type { DevAuthSeam } from './types'

export const renderFixtureApp: DevAuthSeam['renderFixtureApp'] = (children: ReactNode) => (
  <AuthProvider>{children}</AuthProvider>
)

// Keyed by tenant_id so a fixture persona resolves its own tenant the way a real token would.
// Only the TENANT persona appears: the ops persona is PLATFORM and never calls /tenant-self.
// 'Żabka Group' matches the persona's tenantName so the two do not disagree on screen.
export const tenantSelfFixtures: DevAuthSeam['tenantSelfFixtures'] = {
  '019e5e3c-b5d6-7eed-93f9-3778a7a7a160': {
    tenant_id: '019e5e3c-b5d6-7eed-93f9-3778a7a7a160',
    name: 'Żabka Group',
    display_code: 'ZAB',
  },
}

export const signInPath: DevAuthSeam['signInPath'] = '/dev/login'

export const devRoutes: DevAuthSeam['devRoutes'] = [
  // Public, bare (no Shell) — the persona picker that mints a local stub token.
  <Route key="dev-login" path="/dev/login" element={<DevLogin />} />,
] as ReactElement[]
