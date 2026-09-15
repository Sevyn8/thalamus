// P1-SEC-001. The two dev-auth seam variants, asserted directly.
//
// WHY THIS EXISTS ALONGSIDE scripts/assert-no-dev-auth.mjs. That script scans the built
// artifact and is the authority on what shipped; it runs only on `pnpm build`. This file runs
// on every `pnpm test` and pins the CONTRACT: that the production variant is inert, that the
// dev variant is not, and that they expose the same names. A production variant that quietly
// grew a real implementation would still produce a clean bundle scan on the day it was written
// (nothing imports it wrongly yet) and fail later, far from the change.
//
// Both variants are imported BY PATH here rather than through '@devAuthSeam', because the
// point is to compare them. The alias resolves to the dev variant under vitest.

import { describe, expect, it } from 'vitest'

import * as devSeam from './devAuthSeam.dev'
import * as prodSeam from './devAuthSeam.prod'

describe('dev auth seam', () => {
  it('exposes the same exports from both variants', () => {
    // A name present in one and missing from the other is how a production build breaks on an
    // import that type-checked against the dev variant (tsconfig maps @devAuthSeam there).
    expect(Object.keys(prodSeam).sort()).toEqual(Object.keys(devSeam).sort())
  })

  describe('production variant', () => {
    it('contributes no routes, so /dev/login cannot be registered', () => {
      expect(prodSeam.devRoutes).toEqual([])
    })

    it('renders no fixture app, so App falls through to the Auth0 tree', () => {
      // Null rather than a throw: App.tsx does `fixture ?? <RealModeApp />`, so a production
      // artifact built with a missing or misspelled mode string is real-only by construction
      // instead of rendering a broken branch.
      expect(prodSeam.renderFixtureApp(null)).toBeNull()
    })

    it('carries no fixture tenant rows', () => {
      expect(prodSeam.tenantSelfFixtures).toEqual({})
    })

    it('sends unauthenticated callers to the real sign-in route', () => {
      expect(prodSeam.signInPath).toBe('/signin')
      expect(prodSeam.signInPath).not.toContain('/dev/')
    })

    it('contains no dev-auth string material of any kind', () => {
      // Guards the whole surface at once rather than field by field: whatever the production
      // variant grows later, none of it may carry these literals.
      const serialized = JSON.stringify({
        devRoutes: prodSeam.devRoutes,
        tenantSelfFixtures: prodSeam.tenantSelfFixtures,
        signInPath: prodSeam.signInPath,
      })
      for (const forbidden of [
        'dis-ui-dev-stub-secret-not-for-production',
        'customer-master.local',
        'a.kowalski@zabka.pl',
        'anjali@ithina.ai',
        '019e5e3c-b5d6-7eed-93f9-3778a7a7a160',
        '019e5e3c-b633-7344-93c7-83fb205285ea',
        '/dev/login',
      ]) {
        expect(serialized).not.toContain(forbidden)
      }
    })
  })

  describe('development variant', () => {
    // The vacuity half. Every assertion above passes trivially against a seam that does
    // nothing at all; these prove the dev side is still wired, so local fixture auth is
    // preserved rather than quietly removed to make the production scan green.
    it('registers the dev login route', () => {
      expect(devSeam.devRoutes).toHaveLength(1)
      expect(devSeam.signInPath).toBe('/dev/login')
    })

    it('renders a fixture app tree', () => {
      expect(devSeam.renderFixtureApp(null)).not.toBeNull()
    })

    it('carries the persona-linked fixture tenant', () => {
      expect(devSeam.tenantSelfFixtures['019e5e3c-b5d6-7eed-93f9-3778a7a7a160']?.name).toBe(
        'Żabka Group',
      )
    })
  })
})
