import type { MeResponse } from './types'

// Fixture GET /me profile responses, keyed by the token's sub (user_id).
//
// MIRRORS services/dis-ui EXACTLY (dis-ui is authoritative for dev personas + fixtures),
// including its known inconsistency: the ops persona's token sub is 'anjali'
// (auth/dev/personas.ts) but the ops fixture here is keyed 'u_opsdev0001', so getMe() for the
// ops persona throws "no fixture" in fixture mode. This is deliberately NOT reconciled here;
// the shared fix is tracked as D37 (docs/backend-audit-reconciled.md).
//
// These are a standalone map (NOT derived from the /dev/login personas): the profile call is a
// separate dis-ui-server -> Customer Master concern, and the personas model only token claims.
// user_id / tenant_id / tenant_name align to Sanjeev's slice-2 fixtures (Acme Retail =
// t_acme9k2l1mn4). email and name have NO source in Sanjeev's repo (he excludes user display
// fields from the data plane); the values below are UI-dev fixtures, PROVISIONAL and OPEN
// pending the real profile call. Both this map and the personas are fixture-mode artifacts
// that go away when real mode + real Customer Master land.
export const ME_FIXTURES: Record<string, MeResponse> = {
  u_acmeuser0001: {
    user_id: 'u_acmeuser0001',
    email: 'acme.user@example.test',
    name: 'A. Kowalski',
    tenant_id: 't_acme9k2l1mn4',
    tenant_name: 'Żabka Group',
  },
  u_opsdev0001: {
    user_id: 'u_opsdev0001',
    email: 'ops.dev@ithina.test',
    name: 'Ops Dev',
    tenant_id: null,
    tenant_name: null,
  },
}
