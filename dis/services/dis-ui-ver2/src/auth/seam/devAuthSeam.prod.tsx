// PRODUCTION variant of the dev-auth seam. Selected by vite.config.ts for deployable
// production builds.
//
// IT IMPORTS NOTHING FROM src/auth/dev, AND THAT ABSENCE IS THE SECURITY CONTROL.
// The fixture provider, the persona list, the client-side stub signer and the published
// HS256 constant are reachable only through devAuthSeam.dev.tsx, so a build that resolves
// '@devAuthSeam' here cannot emit them into any chunk. scripts/assert-no-dev-auth.mjs
// re-checks the built bytes, because a claim about a module graph is worth less than a
// scan of what actually shipped.
//
// renderFixtureApp returns null rather than throwing: App.tsx falls through to the Auth0
// tree, so a production artifact built with a missing or misspelled mode string is
// structurally real-only instead of rendering a broken fixture branch.

import type { DevAuthSeam } from './types'

// Takes no parameter: the children are discarded, and naming an unused one only invites a
// future edit to start using it.
export const renderFixtureApp: DevAuthSeam['renderFixtureApp'] = () => null

export const signInPath: DevAuthSeam['signInPath'] = '/signin'

export const devRoutes: DevAuthSeam['devRoutes'] = []

export const tenantSelfFixtures: DevAuthSeam['tenantSelfFixtures'] = {}
