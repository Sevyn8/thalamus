import { useState } from 'react'
import { useSearchParams } from 'react-router'

import { getCloverAuthorizeUrl } from '../../../lib/dis-ui-server/clover-oauth'
import { createMappingTemplateIfAbsent } from '../../../lib/dis-ui-server/mapping-templates'
import { createSourceIfAbsent } from '../../../lib/dis-ui-server/sources'
import { JourneyShell } from '../JourneyShell'
import type { JourneyDefinition, JourneyStep } from '../journey'
import {
  CLOVER_APP_MARKET_URL,
  CLOVER_DISPLAY_NAME,
  CLOVER_SOURCE_ID,
  CLOVER_TEMPLATE_NAME,
  SNAPSHOT_COLUMNS,
  writeCloverPending,
} from './config'

// The Clover connect journey, rendered entirely through JourneyShell (D1): this file
// supplies a definition and body content, never a button, card or footer.
//
// FOUR steps, one more than Square, and the extra one is a SIGNPOST rather than a gate:
//   1. Register  - create the api source + the ACTIVE snapshot template (REAL BFF).
//   2. Install   - is the app on the merchant's Clover account? We CANNOT check: we do not
//                  know the merchant until consent completes, so there is nothing to ask
//                  Clover. Two doors, both leading on, neither writing anything.
//   3. Connect   - GET the authorize URL (source_id bound into the signed state) and
//                  window.location to Clover. Clover returns to /connectors/clover/launch.
//   4. First pull - honest affordance: the first pull is operator-run (C4).
//
// WHY INSTALL IS NOT A GATE. If the app is not installed on the merchant, Clover's authorize
// endpoint SILENTLY diverts to the App Market listing rather than erroring - so a wrong
// guess costs exactly one bounce, which the launch route catches and turns into a resume.
// A gate would have to verify something unverifiable, so it would be theatre.
//
// Self-serve TENANT is the primary persona: the tenant is derived server-side from the
// Bearer token and no acted-for field is sent. PLATFORM impersonation remains supported by
// the BFF endpoints for a later ops journey.

type Phase = 'idle' | 'running' | 'error'

// The step indices, named so the URL-driven jumps below read as intent rather than digits.
const STEP_REGISTER = 0
const STEP_INSTALL = 1
const STEP_CONNECT = 2
const STEP_FIRST_PULL = 3

const STEP_META = [
  { title: 'Register', desc: 'Source & mapping template' },
  { title: 'Install', desc: 'Sevyn8 on your Clover account' },
  { title: 'Connect', desc: 'Authorise Clover' },
  { title: 'First pull', desc: 'Verify data lands' },
] as const

export function CloverJourney() {
  const [params] = useSearchParams()

  // The launch route sends the browser back here in one of two shapes: connected (consent
  // finished) or resume-at-connect (installed but not authorised, merchant known).
  const connected = params.get('connected') === '1'
  const resumeAtConnect = params.get('step') === 'connect'
  const merchantId = params.get('merchant_id')

  const [step, setStep] = useState<number>(
    connected ? STEP_FIRST_PULL : resumeAtConnect ? STEP_CONNECT : STEP_REGISTER,
  )
  const [registerPhase, setRegisterPhase] = useState<Phase>('idle')
  const [connectPhase, setConnectPhase] = useState<Phase>('idle')
  const [error, setError] = useState<string | null>(null)
  // Re-entry: on a second pass both the source and the template already exist (each 409,
  // tolerated). Surface a note on the next step instead of a step error.
  const [alreadyRegistered, setAlreadyRegistered] = useState(false)

  async function register(): Promise<void> {
    setRegisterPhase('running')
    setError(null)
    try {
      const sourceCreated = await createSourceIfAbsent({
        source_id: CLOVER_SOURCE_ID,
        display_name: CLOVER_DISPLAY_NAME,
        channel: 'api',
      })
      const templateCreated = await createMappingTemplateIfAbsent({
        source_id: CLOVER_SOURCE_ID,
        template_name: CLOVER_TEMPLATE_NAME,
        template_type: 'snapshot',
        columns: SNAPSHOT_COLUMNS,
      })
      setAlreadyRegistered(!sourceCreated && !templateCreated)
      setRegisterPhase('idle')
      setStep(STEP_INSTALL)
    } catch {
      // D8: client-facing copy. What happened and what to do, one sentence, no error code.
      setError('The Clover source could not be set up. Try again in a moment.')
      setRegisterPhase('error')
    }
  }

  async function connect(): Promise<void> {
    setConnectPhase('running')
    setError(null)
    try {
      const { authorize_url } = await getCloverAuthorizeUrl(CLOVER_SOURCE_ID)
      writeCloverPending({ source_id: CLOVER_SOURCE_ID })
      window.location.href = authorize_url
    } catch {
      setError('Clover could not be reached to start the connection. Try again in a moment.')
      setConnectPhase('error')
    }
  }

  function body(index: number) {
    if (index === STEP_REGISTER) {
      return (
        <p className="sub" style={{ marginBottom: 16 }}>
          Registers the Clover source <span className="mono">{CLOVER_SOURCE_ID}</span> and an
          ACTIVE snapshot mapping template for your catalogue.
        </p>
      )
    }
    if (index === STEP_INSTALL) {
      return (
        <>
          <p className="sub" style={{ marginBottom: 16 }}>
            Is Sevyn8 installed on your Clover account? If you are not sure, open the App Market
            listing - the page says whether it is installed. Nothing is saved on this step
            either way.
          </p>
          <div className="okbox" role="status" style={{ marginBottom: 16 }}>
            Authorising may need a different person. The Clover account holder is often not the
            same person who set up Sevyn8, and only they can approve access.
          </div>
        </>
      )
    }
    if (index === STEP_CONNECT) {
      return (
        <>
          {merchantId !== null ? (
            <div className="okbox" role="status" style={{ marginBottom: 12 }}>
              Sevyn8 is installed on Clover merchant <span className="mono">{merchantId}</span>.
              Authorise access to finish.
            </div>
          ) : null}
          <p className="sub" style={{ marginBottom: 16 }}>
            You will be sent to Clover to authorise read access to your catalogue and inventory.
            Clover returns you here to finish.
          </p>
        </>
      )
    }
    const connectedSourceId = params.get('source_id') ?? CLOVER_SOURCE_ID
    return (
      <>
        <div className="okbox" role="status" style={{ marginBottom: 12 }}>
          Clover is connected for source <span className="mono">{connectedSourceId}</span>
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
      meta: STEP_META[STEP_REGISTER],
      body: body(STEP_REGISTER),
      action: {
        label: 'Register source & template',
        runningLabel: 'Registering...',
        running: registerPhase === 'running',
        onAct: () => void register(),
      },
    },
    {
      // Signpost, not gate: nothing here can be verified and nothing is written (D3).
      kind: 'signpost',
      meta: STEP_META[STEP_INSTALL],
      body: body(STEP_INSTALL),
      actions: [
        {
          label: 'Continue to authorise',
          accent: true,
          onAct: () => setStep(STEP_CONNECT),
        },
        {
          label: 'Open App Market',
          external: true,
          onAct: () => {
            window.open(CLOVER_APP_MARKET_URL, '_blank', 'noopener,noreferrer')
            // Both doors lead onward. Opening the listing in a new tab leaves this one on
            // Connect, so returning from the App Market resumes where the tenant expects.
            setStep(STEP_CONNECT)
          },
        },
      ],
    },
    {
      kind: 'gate',
      meta: STEP_META[STEP_CONNECT],
      body: body(STEP_CONNECT),
      action: {
        label: 'Sign in with Clover',
        runningLabel: 'Redirecting...',
        running: connectPhase === 'running',
        onAct: () => void connect(),
      },
    },
    {
      kind: 'terminal',
      meta: STEP_META[STEP_FIRST_PULL],
      body: body(STEP_FIRST_PULL),
      links: [
        { label: 'View Ingestion Runs', to: '/ingestion-runs' },
        { label: 'Open Canonical Explorer', to: '/canonical' },
      ],
    },
  ]

  const journey: JourneyDefinition = {
    vendorName: 'Clover',
    steps,
    step,
    onJump: (i) => setStep(i),
    error,
    note:
      step === STEP_INSTALL && alreadyRegistered
        ? 'Source and mapping template were already registered. Continue to install and authorise.'
        : null,
  }

  return <JourneyShell journey={journey} />
}
