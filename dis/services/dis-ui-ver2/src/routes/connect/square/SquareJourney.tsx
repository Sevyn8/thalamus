import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'

import { createMappingTemplate } from '../../../lib/dis-ui-server/mapping-templates'
import { createSourceIfAbsent } from '../../../lib/dis-ui-server/sources'
import { getSquareAuthorizeUrl } from '../../../lib/dis-ui-server/square-oauth'
import { StepRail } from '../StepRail'
import type { RailStep } from '../StepRail'
import {
  SNAPSHOT_COLUMNS,
  SQUARE_DISPLAY_NAME,
  SQUARE_PENDING_KEY,
  SQUARE_SOURCE_ID,
  SQUARE_STORE_CODE,
  SQUARE_TEMPLATE_NAME,
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

const STEPS: RailStep[] = [
  { title: 'Register', desc: 'Source & mapping template' },
  { title: 'Connect', desc: 'Authorize Square' },
  { title: 'First pull', desc: 'Verify data lands' },
]

type Phase = 'idle' | 'running' | 'error'

export function SquareJourney() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  // The callback routes back here with ?connected=1 after a successful complete; jump to the
  // first-pull step. A fresh entry starts at Register.
  const connected = params.get('connected') === '1'
  const [step, setStep] = useState<number>(connected ? 2 : 0)
  const [registerPhase, setRegisterPhase] = useState<Phase>('idle')
  const [connectPhase, setConnectPhase] = useState<Phase>('idle')
  const [error, setError] = useState<string | null>(null)

  const merchantId = params.get('merchant_id')
  const connectedSourceId = params.get('source_id') ?? SQUARE_SOURCE_ID
  // A resume hint: set before the OAuth redirect, so returning after a mid-consent login shows
  // that a connect was in progress rather than a blank restart.
  const resuming =
    !connected &&
    typeof sessionStorage !== 'undefined' &&
    sessionStorage.getItem(SQUARE_PENDING_KEY) !== null

  async function register(): Promise<void> {
    setRegisterPhase('running')
    setError(null)
    try {
      await createSourceIfAbsent({
        source_id: SQUARE_SOURCE_ID,
        display_name: SQUARE_DISPLAY_NAME,
        channel: 'api',
        store_id: SQUARE_STORE_CODE,
      })
      await createMappingTemplate({
        source_id: SQUARE_SOURCE_ID,
        template_name: SQUARE_TEMPLATE_NAME,
        template_type: 'snapshot',
        columns: SNAPSHOT_COLUMNS,
      })
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
      const { authorize_url } = await getSquareAuthorizeUrl(SQUARE_SOURCE_ID)
      sessionStorage.setItem(SQUARE_PENDING_KEY, SQUARE_SOURCE_ID)
      window.location.href = authorize_url
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start the Square connection')
      setConnectPhase('error')
    }
  }

  function panel() {
    if (step === 0) {
      return (
        <>
          <p className="sub" style={{ marginBottom: 16 }}>
            Registers the Square source <span className="mono">{SQUARE_SOURCE_ID}</span> and an
            ACTIVE snapshot mapping template for store{' '}
            <span className="mono">{SQUARE_STORE_CODE}</span>.
          </p>
          <button
            type="button"
            className="btn pri"
            onClick={() => void register()}
            disabled={registerPhase === 'running'}
          >
            {registerPhase === 'running' ? 'Registering...' : 'Register source & template'}
          </button>
        </>
      )
    }
    if (step === 1) {
      return (
        <>
          {resuming ? (
            <div className="warnbox" role="note" style={{ marginBottom: 12 }}>
              Resuming your Square connection. Sign in with Square to finish.
            </div>
          ) : null}
          <p className="sub" style={{ marginBottom: 16 }}>
            You will be sent to Square to authorize read access (locations, catalogue, inventory,
            orders). Square returns you here to finish.
          </p>
          <button
            type="button"
            className="btn pri"
            onClick={() => void connect()}
            disabled={connectPhase === 'running'}
          >
            {connectPhase === 'running' ? 'Redirecting...' : 'Sign in with Square'}
          </button>
        </>
      )
    }
    // step 2: first pull (honest affordance)
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
        <div className="wizfoot" style={{ justifyContent: 'flex-start', gap: 12 }}>
          <Link className="btn" to="/ingestion-runs">
            View Ingestion Runs
          </Link>
          <Link className="btn" to="/canonical">
            Open Canonical Explorer
          </Link>
        </div>
      </>
    )
  }

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Connect Square</h1>
        </div>
      </div>
      <div className="wizwrap">
        <StepRail steps={STEPS} current={step} onJump={(i) => setStep(i)} />
        <div>
          <h2 className="text-lg font-semibold" style={{ marginBottom: 4 }}>
            {STEPS[step].title}
          </h2>
          <p className="sub" style={{ marginBottom: 16 }}>
            {STEPS[step].desc}
          </p>
          {error !== null ? (
            <p role="alert" className="text-sm text-red-600" style={{ marginBottom: 12 }}>
              {error}
            </p>
          ) : null}
          {panel()}
          <div className="wizfoot">
            <button type="button" className="btn" onClick={() => navigate('/connect')}>
              Back to sources
            </button>
          </div>
        </div>
      </div>
    </>
  )
}
