import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router'

import { useAuth } from '../../../auth/useAuth'
import { createMappingTemplateIfAbsent } from '../../../lib/dis-ui-server/mapping-templates'
import { createSourceIfAbsent, useSources } from '../../../lib/dis-ui-server/sources'
import { getSquareAuthorizeUrl } from '../../../lib/dis-ui-server/square-oauth'
import {
  useStoresOnboarded,
  useStoresOnboardedForTenant,
} from '../../../lib/dis-ui-server/stores'
import type { OnboardedStore } from '../../../lib/dis-ui-server/stores'
import { distinctTenants, tenantName } from '../../../lib/dis-ui-server/tenant-label'
import { JourneyShell } from '../JourneyShell'
import type { JourneyDefinition, JourneyStep } from '../journey'
import {
  readSquarePending,
  SNAPSHOT_COLUMNS,
  SQUARE_DISPLAY_NAME,
  SQUARE_SOURCE_ID,
  SQUARE_TEMPLATE_NAME,
  writeSquarePending,
} from './config'

// The Square connect journey (its own route/component tree; reuses the StepRail primitive).
// Three steps:
//   1. Register  - create the api source + the ACTIVE snapshot template (REAL BFF: POST /sources,
//                  POST /mapping-templates), the same equivalence-proven pattern as OnboardSquare.
//   2. Connect   - GET the Square authorize URL (REAL BFF, source_id bound into the signed state)
//                  and window.location to Square. Square redirects to /connectors/square/callback,
//                  which POSTs /complete (writes the token vault) and routes back here (?connected=1).
//   3. First pull - honest affordance: the first pull is operator-run (no scheduler yet, S4); links
//                  to Ingestion Runs (status) and Canonical Explorer (the acceptance target).
//
// Persona: a PLATFORM (ops) caller connects a CLIENT's Square, so it must name the acted-for
// tenant on every write/connect call (resolve_acted_for on the BFF; a missing one is 403
// tenant_scope). The Register step surfaces a tenant picker sourced from the sources list (the
// cleanest existing PLATFORM-readable, tenant-attributed read); the selection threads through
// register + mapping-template + authorize-url and into the resume hint. A TENANT caller never
// sends the field (the server pins its own tenant; naming one is a 403).

const STEP_META = [
  { title: 'Register', desc: 'Source & mapping template' },
  { title: 'Connect', desc: 'Authorize Square' },
  { title: 'First pull', desc: 'Verify data lands' },
] as const

type Phase = 'idle' | 'running' | 'error'

export function SquareJourney() {
  const [params] = useSearchParams()
  const { snapshot } = useAuth()
  const isPlatform = snapshot?.userType === 'PLATFORM'

  // The callback routes back here with ?connected=1 after a successful complete; jump to the
  // first-pull step. A fresh entry starts at Register.
  const connected = params.get('connected') === '1'
  const [step, setStep] = useState<number>(connected ? 2 : 0)
  const [registerPhase, setRegisterPhase] = useState<Phase>('idle')
  const [connectPhase, setConnectPhase] = useState<Phase>('idle')
  const [error, setError] = useState<string | null>(null)
  // Re-entry: on a second pass both the source and the template already exist (each 409,
  // tolerated). Surface an "already registered" note on Connect instead of a step error.
  const [alreadyRegistered, setAlreadyRegistered] = useState(false)

  // PLATFORM tenant picker: distinct tenants from the sources list (auto-populated, no new
  // endpoint). Pre-select the resume hint's tenant when returning mid-connect.
  const sourcesQuery = useSources(snapshot)
  const [selectedTenant, setSelectedTenant] = useState<string>(
    () => readSquarePending()?.acting_for_tenant_id ?? '',
  )
  const tenantOptions = useMemo(() => {
    const rows = sourcesQuery.data ?? []
    const nameById = new Map<string, string | null>()
    for (const row of rows) {
      if (!nameById.has(row.tenant_id)) nameById.set(row.tenant_id, row.tenant_name ?? null)
    }
    return distinctTenants([...nameById.keys()])
      .filter((id): id is string => id !== null)
      .map((id) => ({ id, label: tenantName(nameById.get(id) ?? null, id) }))
  }, [sourcesQuery.data])

  // The acted-for tenant sent to the BFF: the PLATFORM selection, or undefined for a TENANT
  // caller (the field is then omitted from every call).
  const actedFor = isPlatform && selectedTenant !== '' ? selectedTenant : undefined
  const platformNeedsTenant = isPlatform && selectedTenant === ''

  // Store selection (replaces the retired W-001 hardcode; the seeded DIS store is AMB-001 now).
  // TENANT reads its own onboarded stores; PLATFORM reads the acted-for tenant's stores via the
  // cross-tenant endpoint (gated on the tenant selection). Exactly one query fires per persona:
  // the other is passed null so it stays disabled (a PLATFORM caller must never hit the
  // token-tenant-pinned /stores-onboarded, which 403s for it).
  const tenantStoresQuery = useStoresOnboarded(isPlatform ? null : snapshot)
  const platformStoresQuery = useStoresOnboardedForTenant(
    snapshot,
    isPlatform ? (selectedTenant === '' ? null : selectedTenant) : null,
  )
  const storesQuery = isPlatform ? platformStoresQuery : tenantStoresQuery

  const [selectedStore, setSelectedStore] = useState('')
  // Only stores with a store_code are selectable (store_code is the source's store_id; a NULL
  // code, D55, cannot be a source key). Label pairs the name with the code for disambiguation.
  const storeOptions = useMemo(
    () =>
      (storesQuery.data ?? [])
        .filter((s): s is OnboardedStore & { store_code: string } => s.store_code !== null)
        .map((s) => ({ code: s.store_code, label: `${s.name} (${s.store_code})` })),
    [storesQuery.data],
  )
  // Single store auto-selects (derived, no effect): the explicit pick wins, else the sole
  // option, else empty (multi-store requires an explicit pick before Register enables).
  const effectiveStore =
    selectedStore !== '' ? selectedStore : storeOptions.length === 1 ? storeOptions[0].code : ''
  const needsStore = effectiveStore === ''

  async function register(): Promise<void> {
    setRegisterPhase('running')
    setError(null)
    try {
      const sourceCreated = await createSourceIfAbsent({
        source_id: SQUARE_SOURCE_ID,
        display_name: SQUARE_DISPLAY_NAME,
        channel: 'api',
        store_id: effectiveStore,
        acting_for_tenant_id: actedFor,
      })
      // Idempotent on re-entry: the template create is 409-tolerant (name already used by a
      // prior run's template of this source), the same posture as the source create above.
      const templateCreated = await createMappingTemplateIfAbsent({
        source_id: SQUARE_SOURCE_ID,
        template_name: SQUARE_TEMPLATE_NAME,
        template_type: 'snapshot',
        columns: SNAPSHOT_COLUMNS,
        acting_for_tenant_id: actedFor,
      })
      setAlreadyRegistered(!sourceCreated && !templateCreated)
      setRegisterPhase('idle')
      setStep(1)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Registration failed')
      setRegisterPhase('error')
    }
  }

  async function connect(): Promise<void> {
    setConnectPhase('running')
    setError(null)
    try {
      const { authorize_url } = await getSquareAuthorizeUrl(SQUARE_SOURCE_ID, actedFor)
      writeSquarePending({ source_id: SQUARE_SOURCE_ID, acting_for_tenant_id: actedFor ?? null })
      window.location.href = authorize_url
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start the Square connection')
      setConnectPhase('error')
    }
  }

  function tenantPicker() {
    if (!isPlatform) return null
    return (
      <div className="field" style={{ marginBottom: 16 }}>
        <label htmlFor="sq-tenant">Tenant to connect</label>
        {sourcesQuery.isPending ? (
          <span className="hint">Loading tenants...</span>
        ) : tenantOptions.length === 0 ? (
          <span className="hint">
            No tenants available to connect. A tenant needs at least one registered source to
            appear here.
          </span>
        ) : (
          <select
            id="sq-tenant"
            value={selectedTenant}
            onChange={(e) => setSelectedTenant(e.target.value)}
          >
            <option value="">Select a tenant...</option>
            {tenantOptions.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label}
              </option>
            ))}
          </select>
        )}
      </div>
    )
  }

  function storePicker() {
    // Not shown until a PLATFORM caller has picked a tenant (the store read is gated on it).
    if (isPlatform && selectedTenant === '') return null
    return (
      <div className="field" style={{ marginBottom: 16 }}>
        <label htmlFor="sq-store">Store to connect</label>
        {storesQuery.isPending ? (
          <span className="hint">Loading stores...</span>
        ) : storeOptions.length === 0 ? (
          <span className="hint">
            No onboarded store with a store code is available for this tenant.
          </span>
        ) : (
          <select
            id="sq-store"
            value={effectiveStore}
            onChange={(e) => setSelectedStore(e.target.value)}
          >
            {storeOptions.length > 1 ? <option value="">Select a store...</option> : null}
            {storeOptions.map((s) => (
              <option key={s.code} value={s.code}>
                {s.label}
              </option>
            ))}
          </select>
        )}
      </div>
    )
  }

  // Body content only: no button, no card, no footer. The shell owns all of those, so the
  // three journeys cannot drift on chrome (D1).
  function body(index: number) {
    if (index === 0) {
      return (
        <>
          <p className="sub" style={{ marginBottom: 16 }}>
            Registers the Square source <span className="mono">{SQUARE_SOURCE_ID}</span> and an
            ACTIVE snapshot mapping template for the selected store.
          </p>
          {tenantPicker()}
          {storePicker()}
        </>
      )
    }
    if (index === 1) {
      return (
        <p className="sub" style={{ marginBottom: 16 }}>
          You will be sent to Square to authorize read access (locations, catalogue, inventory,
          orders). Square returns you here to finish.
        </p>
      )
    }
    // step 2: first pull (honest affordance)
    const connectedSourceId = params.get('source_id') ?? SQUARE_SOURCE_ID
    const merchantId = params.get('merchant_id')
    return (
      <>
        <div className="okbox" role="status" style={{ marginBottom: 12 }}>
          Square is connected for source <span className="mono">{connectedSourceId}</span>
          {merchantId !== null ? (
            <>
              {' '}
              (merchant <span className="mono">{merchantId}</span>)
            </>
          ) : null}
          .
        </div>
        <p className="sub" style={{ marginBottom: 16 }}>
          The first pull is operator-run today (no scheduler yet). Once a run completes, review it
          here:
        </p>
      </>
    )
  }

  const steps: JourneyStep[] = [
    {
      kind: 'gate',
      meta: STEP_META[0],
      body: body(0),
      action: {
        label: 'Register source & template',
        runningLabel: 'Registering...',
        running: registerPhase === 'running',
        disabled: platformNeedsTenant || needsStore,
        onAct: () => void register(),
      },
    },
    {
      kind: 'gate',
      meta: STEP_META[1],
      body: body(1),
      action: {
        label: 'Sign in with Square',
        runningLabel: 'Redirecting...',
        running: connectPhase === 'running',
        onAct: () => void connect(),
      },
    },
    {
      kind: 'terminal',
      meta: STEP_META[2],
      body: body(2),
      links: [
        { label: 'View Ingestion Runs', to: '/ingestion-runs' },
        { label: 'Open Canonical Explorer', to: '/canonical' },
      ],
    },
  ]

  const journey: JourneyDefinition = {
    vendorName: 'Square',
    steps,
    step,
    onJump: (i) => setStep(i),
    error,
    // The re-entry note belongs to the Connect step only: it is what a second pass through
    // Register produces, and it is read on the step after it.
    note:
      step === 1 && alreadyRegistered
        ? 'Source and mapping template were already registered. Continue to authorize Square.'
        : null,
  }

  return <JourneyShell journey={journey} />
}
