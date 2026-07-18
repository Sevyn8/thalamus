import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { LoadingState } from '../../components/states/LoadingState'
import {
  fetchLocations,
  fetchMappingSuggestions,
  fetchPreviewRows,
} from '../../lib/dis-ui-server/connectors-api'
import {
  CONNECTOR_ORDER,
  CONNECTOR_SPECS,
} from '../../lib/dis-ui-server/connectors-catalog'
import type { ConnectorKey } from '../../lib/dis-ui-server/connectors-catalog'
import { StepRail } from './StepRail'
import type { RailStep } from './StepRail'

// POS / native-connector wizard, mockup-shaped (full 9-step rail). This is a DESIGNED
// WALKTHROUGH on placeholder data: dis-ui's POS branch is entirely TODO(wire) stubs (no
// connector endpoints exist on main), so every connection/inspection step here is presented as
// pending-backend, NOT as real work. Honesty guardrail: a persistent banner + per-step markers;
// no fake "Connected ✓", no invented live account/location data claimed as real. The stub
// fixtures (fetchLocations/fetchMappingSuggestions/fetchPreviewRows) are dis-ui's, reskinned.

const STEPS: RailStep[] = [
  { title: 'Source & method', desc: 'Native connector' },
  { title: 'Configure', desc: 'Vendor & auth' },
  { title: 'Test connection', desc: 'Verify access' },
  { title: 'Inspect data', desc: 'Raw snapshot' },
  { title: 'Parsing profile', desc: 'Locale & formats' },
  { title: 'Data type', desc: 'What this represents' },
  { title: 'AI mapping', desc: 'Source to canonical' },
  { title: 'Preview', desc: 'Validate before activation' },
  { title: 'Activate', desc: 'Go live' },
]

function PendingNote({ what }: { what: string }) {
  return (
    <div className="warnbox" role="note" style={{ marginBottom: 12 }}>
      Preview — {what} isn’t connected to a live source yet. The data shown is an example.
    </div>
  )
}

export function PosWizard({ onBack }: { onBack: () => void }) {
  const [step, setStep] = useState(1)
  const [vendor, setVendor] = useState<ConnectorKey>('square')

  const locations = useQuery({
    queryKey: ['pos-stub-locations', vendor],
    queryFn: () => fetchLocations(vendor),
    enabled: step === 3,
    retry: false,
  })
  const mapping = useQuery({
    queryKey: ['pos-stub-mapping', vendor],
    queryFn: () => fetchMappingSuggestions(vendor, ['orders']),
    enabled: step === 6,
    retry: false,
  })
  const preview = useQuery({
    queryKey: ['pos-stub-preview', vendor],
    queryFn: fetchPreviewRows,
    enabled: step === 7,
    retry: false,
  })

  const spec = CONNECTOR_SPECS[vendor]
  const next = () => setStep((s) => Math.min(s + 1, STEPS.length - 1))
  const back = () => setStep((s) => (s <= 1 ? (onBack(), 0) : s - 1))

  function panel() {
    switch (step) {
      case 1:
        return (
          <div className="choicegrid">
            {CONNECTOR_ORDER.map((k) => (
              <button
                key={k}
                type="button"
                className={`choice ${vendor === k ? 'on' : ''}`}
                onClick={() => setVendor(k)}
              >
                <div className="ic">{CONNECTOR_SPECS[k].icon}</div>
                <div className="t">{CONNECTOR_SPECS[k].label}</div>
                <div className="d">{CONNECTOR_SPECS[k].description}</div>
              </button>
            ))}
          </div>
        )
      case 2:
        return (
          <>
            <PendingNote what="OAuth / API-token sign-in" />
            <div className="field">
              <label>{spec.oauthLabel}</label>
              <span className="hint">What you’ll need: {spec.whatYouWillNeed.join('; ')}</span>
            </div>
            <button type="button" className="btn" disabled>
              {spec.oauthLabel} (pending)
            </button>
          </>
        )
      case 3:
        return (
          <>
            <PendingNote what="connection test" />
            <div className="empty">Connection test isn’t available in this preview.</div>
          </>
        )
      case 4:
        return (
          <>
            <PendingNote what="location / data inspection" />
            {locations.isPending ? (
              <LoadingState label="Loading example locations…" />
            ) : (
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Location (example)</th>
                    <th>Address</th>
                  </tr>
                </thead>
                <tbody>
                  {(locations.data ?? []).map((l) => (
                    <tr key={l.id}>
                      <td className="pri-name">{l.name}</td>
                      <td className="id">{l.address}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )
      case 5:
        return (
          <>
            <PendingNote what="parsing profile" />
            <div className="empty">Locale &amp; format detection arrives with the live connector.</div>
          </>
        )
      case 6:
        return (
          <>
            <PendingNote what="AI mapping (available once a live sample exists)" />
            {mapping.isPending ? (
              <LoadingState label="Loading example mapping…" />
            ) : (
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Source field (example)</th>
                    <th>Suggested target</th>
                  </tr>
                </thead>
                <tbody>
                  {(mapping.data?.fields ?? []).map((f) => (
                    <tr key={f.sourceField}>
                      <td className="id">{f.sourceField}</td>
                      <td>
                        <span className="badge b-mut">{f.suggestedTarget ?? 'ignore'}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )
      case 7:
        return (
          <>
            <PendingNote what="canonical preview" />
            {preview.isPending ? (
              <LoadingState label="Loading example preview…" />
            ) : (
              <div className="empty">
                {(preview.data ?? []).length} example preview rows.
              </div>
            )}
          </>
        )
      case 8:
        return (
          <>
            <PendingNote what="go-live / connector provisioning" />
            <div className="empty">
              Activation provisions the connector and its sync schedule.
            </div>
          </>
        )
      default:
        return null
    }
  }

  return (
    <div className="wizwrap">
      <StepRail steps={STEPS} current={step} onJump={(i) => (i === 0 ? onBack() : setStep(i))} />
      <div>
        <div className="warnbox" role="note" style={{ marginBottom: 14 }}>
          <b>Preview.</b> This connector flow shows example data — no live connection is made
          yet.
        </div>
        <h2 className="text-lg font-semibold" style={{ marginBottom: 4 }}>
          {STEPS[step].title}
        </h2>
        <p className="sub" style={{ marginBottom: 16 }}>
          {STEPS[step].desc}
        </p>
        {panel()}
        <div className="wizfoot">
          <button type="button" className="btn" onClick={back}>
            Back
          </button>
          {step < STEPS.length - 1 ? (
            <button type="button" className="btn pri" onClick={next}>
              Continue
            </button>
          ) : null}
        </div>
      </div>
    </div>
  )
}
