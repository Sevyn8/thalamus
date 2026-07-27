import { useQuery } from '@tanstack/react-query'

import type { AuthSnapshot } from '../../auth/AuthSnapshot'
import { getJson } from './client'
import { isRealMode } from './mode'

// The actable-tenant list (GET /api/v1/tenants-actable). Shaped EXACTLY to the real contract
// (services/dis-ui-server/.../schemas/tenants.py:ActableTenant), served as a bare array,
// PLATFORM-ops only. Mode-aware: real mode calls the live endpoint; fixture mode returns the
// inlined rows so local dev + tests need no backend.
//
// WHY THIS EXISTS RATHER THAN REUSING useSources. The connect journeys' tenant picker used to
// be built from the sources list — distinct tenant_ids among the rows — which quietly made it
// "every tenant that ALREADY HAS a source". That is the complement of the onboarding case: a
// freshly onboarded tenant with zero sources never appeared, so nobody could connect its FIRST
// source. The list has to come from the tenant mirror, not from a by-product of another read.
//
// Backed by identity_mirror.tenants, so it is only as complete as the mirror — and
// mirror-sync-consumer is not deployed, so today that is the hand-seeded rows.

// TERMINATED is excluded server-side (an end state has no onboarding to act for) and is
// absent from this union for the same reason it is absent from the wire Literal.
export type TenantStatus = 'onboarding' | 'trial' | 'active' | 'suspended'

export type ActableTenant = {
  tenant_id: string // internal UUID, lowercase string — the acted-for id
  name: string
  display_code: string | null // nullable at source (D55), served as-is
  status: TenantStatus
}

// Fixture rows, ordered by name as the backend orders them. Two entries are deliberate rather
// than filler: "Brand New Co" has NO sources fixture (the onboarding case this endpoint exists
// for) and "Paused Partners" is SUSPENDED (the picker must show it disabled, not hide it).
const TENANT_FIXTURES: ActableTenant[] = [
  {
    tenant_id: '0190ac10-1a01-7001-8a01-0000000000a1',
    name: 'Acme Retail',
    display_code: 'ACME',
    status: 'active',
  },
  {
    tenant_id: '0190ac10-1a01-7001-8a01-0000000000c3',
    name: 'Brand New Co',
    display_code: null,
    status: 'onboarding',
  },
  {
    tenant_id: '0190ac10-1a01-7001-8a01-0000000000d4',
    name: 'Paused Partners',
    display_code: 'PAUSE',
    status: 'suspended',
  },
  {
    tenant_id: '0190ac10-1a01-7001-8a01-0000000000b2',
    name: 'Zabka Group',
    display_code: 'ZAB',
    status: 'active',
  },
]

export async function getActableTenants(): Promise<ActableTenant[]> {
  if (isRealMode()) {
    return getJson<ActableTenant[]>('/api/v1/tenants-actable')
  }
  return [...TENANT_FIXTURES]
}

// PLATFORM-only by construction: the endpoint 403s a TENANT caller, so the query is DISABLED
// for one rather than firing and failing. A TENANT journey renders no tenant picker at all,
// so there is nothing for it to have fetched.
export function useActableTenants(snapshot: AuthSnapshot | null) {
  return useQuery({
    queryKey: ['dis-ui-server', 'tenants-actable'],
    queryFn: getActableTenants,
    enabled: snapshot !== null && snapshot.userType === 'PLATFORM',
    staleTime: Infinity,
    retry: false,
  })
}
