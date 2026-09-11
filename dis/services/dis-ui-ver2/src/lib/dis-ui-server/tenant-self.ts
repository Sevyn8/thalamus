import { useQuery } from '@tanstack/react-query'

import type { AuthSnapshot } from '../../auth/AuthSnapshot'
import { getJson } from './client'
import { isRealMode } from './mode'

// The caller's OWN tenant (GET /api/v1/tenant-self). Shaped EXACTLY to the real contract
// (services/dis-ui-server/.../schemas/tenants.py:TenantSelf). Mode-aware: real mode calls the
// live endpoint; fixture mode resolves from the inlined rows so local dev + tests need no
// backend.
//
// WHY THIS EXISTS RATHER THAN REUSING SOMETHING. The topbar renders on EVERY route, so the
// tenant name cannot come from a page-specific response: /dashboard/metrics would leave the
// chip blank until the dashboard loaded and wrong on a deep-link to /connect, and /sources,
// /stores-onboarded and /runs are all legitimately EMPTY for a freshly onboarded tenant —
// which is exactly the tenant whose name we most need. /tenants-actable is not an option
// either: it is a cross-tenant PLATFORM-ops list and 403s a TENANT caller.
//
// Backed by identity_mirror.tenants, which mirror-sync-consumer populates from Customer
// Master. The mirror is EVENTUALLY CONSISTENT, so name/display_code are nullable and a
// missing row is served as a 200 with nulls, never a 404 — the caller falls back to the UUID
// it already holds in the token rather than taking an error path over ordinary sync lag.

export type TenantSelf = {
  tenant_id: string // the caller's own tenant, echoed from the verified token
  name: string | null // null when the mirror has no row yet (lag), not an error
  display_code: string | null // nullable at source, served as-is
}

// Fixture rows keyed by tenant_id, so a fixture persona resolves the same way a real token
// would. Only the tenant persona's id is present: the ops persona is PLATFORM and never calls
// this. 'Żabka Group' matches the persona's own tenantName so the two do not disagree on
// screen.
const TENANT_SELF_FIXTURES: Record<string, TenantSelf> = {
  '019e5e3c-b5d6-7eed-93f9-3778a7a7a160': {
    tenant_id: '019e5e3c-b5d6-7eed-93f9-3778a7a7a160',
    name: 'Żabka Group',
    display_code: 'ZAB',
  },
}

export async function getTenantSelf(tenantId: string): Promise<TenantSelf> {
  if (isRealMode()) {
    return getJson<TenantSelf>('/api/v1/tenant-self')
  }
  // An unknown fixture tenant deliberately resolves to nulls rather than throwing: that is
  // the same shape the real endpoint serves for an unmirrored tenant, so the fallback chain
  // in the topbar is exercised locally instead of only in production.
  return (
    TENANT_SELF_FIXTURES[tenantId] ?? { tenant_id: tenantId, name: null, display_code: null }
  )
}

// TENANT-only by construction: the endpoint 403s a PLATFORM caller (a PLATFORM token has no
// own tenant), so the query is DISABLED for one rather than firing and failing. The PLATFORM
// topbar reads "Scope: All tenants" and has nothing to fetch.
export function useTenantSelf(snapshot: AuthSnapshot | null) {
  const tenantId = snapshot?.tenantId ?? null
  return useQuery({
    queryKey: ['dis-ui-server', 'tenant-self', tenantId],
    queryFn: () => getTenantSelf(tenantId as string),
    enabled: tenantId !== null,
    // The tenant's own name is about as stable as data gets, and a stale name is harmless
    // next to a refetch on every route change (the topbar mounts everywhere).
    staleTime: 5 * 60 * 1000,
  })
}
