import { useAuth } from '../../auth/useAuth'
import { useActableTenants } from '../../lib/dis-ui-server/tenants'
import type { ActableTenant } from '../../lib/dis-ui-server/tenants'
import { tenantName } from '../../lib/dis-ui-server/tenant-label'

// The acted-for tenant picker: which CLIENT a PLATFORM ops caller is connecting a source for.
// Rendered by every connect journey; renders NOTHING for a TENANT caller, whose tenant is
// derived server-side from the Bearer and who must never name one (a 403 at resolve_acted_for).
//
// WHY THIS IS BODY CONTENT AND NOT PART OF JourneyShell. The shell owns chrome so the journeys
// cannot drift on it (D1), and at a glance a picker looks like chrome. It is not: its VALUE is
// business data the vendor consumes — the acted-for tenant threads into createSourceIfAbsent,
// createMappingTemplateIfAbsent and the authorize-url call, and it gates the vendor's own
// cross-tenant store read. Hosting it in the shell would mean the shell produces state the
// vendor's API calls depend on, which is ownership inversion; the shell would then have to know
// which step is the "register" step and hand a value back up. So the shell stays chrome-only and
// this is a shared component both journeys MOUNT — one implementation, no inversion.
//
// The forward-action gate stays with the vendor for the same reason: `disabled` on a GateStep is
// the vendor's predicate over its own preconditions (tenant AND store), not something the shell
// or this component can decide.

type Props = {
  // Unique per journey (the label's htmlFor target); vendors namespace it, e.g. 'sq-tenant'.
  id: string
  value: string
  onChange: (tenantId: string) => void
}

// Name first (honest UUID-tail fallback when the mirror has no name — never a fabricated one),
// then the external code when there is one. A SUSPENDED tenant says so IN THE LABEL: the option
// is disabled, and a disabled option with no reason is just a tenant that mysteriously cannot be
// chosen.
function label(tenant: ActableTenant): string {
  const base =
    tenant.display_code === null
      ? tenantName(tenant.name, tenant.tenant_id)
      : `${tenantName(tenant.name, tenant.tenant_id)} (${tenant.display_code})`
  return tenant.status === 'suspended' ? `${base} — suspended` : base
}

export function ActedForPicker({ id, value, onChange }: Props) {
  const { snapshot } = useAuth()
  const isPlatform = snapshot?.userType === 'PLATFORM'
  // Called unconditionally (hook rules); disabled for a non-PLATFORM caller inside the hook, so
  // a TENANT render fetches nothing.
  const tenantsQuery = useActableTenants(snapshot)

  if (!isPlatform) return null

  const tenants = tenantsQuery.data ?? []

  return (
    <div className="field" style={{ marginBottom: 16 }}>
      <label htmlFor={id}>Tenant to connect</label>
      {tenantsQuery.isPending ? (
        <span className="hint">Loading tenants...</span>
      ) : tenantsQuery.isError ? (
        // An unexplained spinner is what made the Clover journey a dead end; a failed read has
        // to say so and say what to do (D8: no error code, no first person).
        <span className="hint" role="alert">
          The list of tenants could not be loaded. Reload the page to try again.
        </span>
      ) : tenants.length === 0 ? (
        <span className="hint">
          No tenants are available to connect. A tenant must exist in DIS before a source can be
          connected for it.
        </span>
      ) : (
        <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
          <option value="">Select a tenant...</option>
          {tenants.map((t) => (
            <option key={t.tenant_id} value={t.tenant_id} disabled={t.status === 'suspended'}>
              {label(t)}
            </option>
          ))}
        </select>
      )}
    </div>
  )
}
