import { Link, useNavigate } from 'react-router'

import type { JourneyDefinition, JourneyStep } from './journey'
import { StepRail } from './StepRail'
import type { RailStep } from './StepRail'

// The shared connect-journey chrome (D1). EVERY vendor journey renders through this and
// supplies only a JourneyDefinition: ordered steps, body content, the forward action's
// labels and enablement, and the vendor name.
//
// The shell owns, with no vendor override: the page head, the wizwrap grid, the step rail,
// the panel heading and blurb, the error line, the re-entry note, the single accent forward
// action per panel, the terminal link row, and the trailing Back footer. A vendor cannot
// render a raw button, a bare card or a footer of its own - that is the point. Sameness is
// the requirement here, so divergence is a defect rather than a variation, and a shared
// component is the spec.
//
// Extracted from SquareJourney with zero behaviour change: the markup below is that
// journey's, verbatim, with the vendor-specific parts lifted into the definition. StepRail
// is imported unchanged - it was already the right seed.
//
// COPY VOICE, enforced here by construction rather than by review: sentence case,
// verb-first, no "successfully", no exclamation marks. The shell supplies no adjectives; a
// vendor supplies only sentences it wrote, so the only copy the shell can get wrong is the
// Back label.

function railSteps(steps: JourneyStep[]): RailStep[] {
  return steps.map((s) => ({ title: s.meta.title, desc: s.meta.desc }))
}

function StepActions({ step }: { step: JourneyStep }) {
  if (step.kind === 'gate') {
    const { label, runningLabel, running, disabled, onAct } = step.action
    return (
      <button
        type="button"
        className="btn pri"
        onClick={onAct}
        disabled={running || disabled === true}
      >
        {running ? runningLabel : label}
      </button>
    )
  }
  if (step.kind === 'signpost') {
    // Both doors lead onward; at most the first accent one is the primary. A signpost
    // verifies nothing and writes nothing, so neither door is a commitment.
    return (
      <div className="flex gap-3">
        {step.actions.map((action) => (
          <button
            key={action.label}
            type="button"
            className={action.accent === true ? 'btn pri' : 'btn'}
            onClick={action.onAct}
          >
            {action.label}
          </button>
        ))}
      </div>
    )
  }
  // terminal: no forward action, only where to go next. A body content row, not a footer -
  // the panel's single footer rule belongs to the Back row below.
  return (
    <div className="flex gap-3">
      {step.links.map((link) => (
        <Link key={link.to} className="btn" to={link.to}>
          {link.label}
        </Link>
      ))}
    </div>
  )
}

export function JourneyShell({ journey }: { journey: JourneyDefinition }) {
  const navigate = useNavigate()
  const { vendorName, steps, step, onJump, error, note } = journey
  const current = steps[step]

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Connect {vendorName}</h1>
        </div>
      </div>
      <div className="wizwrap">
        <StepRail steps={railSteps(steps)} current={step} onJump={onJump} />
        <div>
          <h2 className="text-lg font-semibold" style={{ marginBottom: 4 }}>
            {current.meta.title}
          </h2>
          <p className="sub" style={{ marginBottom: 16 }}>
            {current.meta.desc}
          </p>
          {error !== null ? (
            <p role="alert" className="text-sm text-red-600" style={{ marginBottom: 12 }}>
              {error}
            </p>
          ) : null}
          {note !== null && note !== undefined ? (
            <div className="okbox" role="status" style={{ marginBottom: 12 }}>
              {note}
            </div>
          ) : null}
          {current.body}
          <StepActions step={current} />
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
