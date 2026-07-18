// DEV ONLY. The personas offered at /dev/login. Each models the Customer Master
// token claim set Sanjeev's slice-2 fakes pin (sub, tenant_id, store_id, roles -
// PROVISIONAL pending decisions.md D25). The name/email/roleLabel/tenantName fields
// below are DEV-ONLY presentation data for the login cards, NOT token claims.

import type { UserType } from '../AuthSnapshot'

export type StubPersona = {
  id: string
  label: string
  sub: string
  // null for ops (cross-tenant). tenant_id/store_id carry the INTERNAL UUIDs the
  // backend RLS keys on (app.tenant_id, D91): the TENANT persona uses the real
  // seeded Żabka / W-001 UUIDs so a runtime-minted token authorizes against the
  // rows the spine provisioned. sub stays the external u_* login id.
  tenant_id: string | null
  store_id: string | null
  // The token's user_type claim (D91): the backend's tenant-vs-ops discriminator, and
  // what isOps() keys on. Matches CM coherence — PLATFORM carries no tenant_id, TENANT does.
  user_type: UserType
  roles: string[]
  // DEV-ONLY presentation fields for the /dev/login cards. Not token claims.
  name: string
  email: string
  roleLabel: string
  tenantName: string | null
}

export const PERSONAS: StubPersona[] = [
  {
    // The real seeded Żabka tenant + W-001 store (the UUIDs the spine provisioned
    // against; libs/dis-testing seed). The token's tenant_id/store_id claims become
    // the backend RLS GUCs, so these MUST be the internal UUIDs, not external codes.
    id: 'tenant',
    label: 'Tenant user (Żabka)',
    sub: 'u_acmeuser0001',
    tenant_id: '019e5e3c-b5d6-7eed-93f9-3778a7a7a160',
    store_id: '019e5e3c-b633-7344-93c7-83fb205285ea',
    user_type: 'TENANT',
    roles: ['dis:upload', 'dis:read'],
    name: 'A. Kowalski',
    email: 'a.kowalski@zabka.pl',
    roleLabel: 'TENANT',
    tenantName: 'Żabka Group',
  },
  {
    // DEV-ONLY platform/superadmin identity, presented as Anjali to match CM's PLATFORM
    // persona (anjali@ithina.ai). Cross-tenant, so tenant_id/store_id null. id stays 'ops'.
    id: 'ops',
    label: 'Anjali (Platform)',
    sub: 'anjali',
    tenant_id: null,
    store_id: null,
    user_type: 'PLATFORM',
    roles: ['dis:ops', 'dis:read', 'dis:mapping_admin'],
    name: 'Anjali Mehta',
    email: 'anjali@ithina.ai',
    roleLabel: 'PLATFORM',
    tenantName: null,
  },
]
