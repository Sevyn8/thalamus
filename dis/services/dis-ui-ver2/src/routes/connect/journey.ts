import type { ReactNode } from 'react'

// The typed journey definition a vendor hands to JourneyShell (D1).
//
// WHAT A VENDOR MAY SUPPLY IS DELIBERATELY NARROW: ordered steps with labels, a per-step
// body, and the forward action's LABELS and ENABLEMENT - never the control itself. Vendors
// cannot render a raw button, a bare card, a callout or a footer. If they could, the
// journeys drift within a month and copy and spacing go first: the chrome is where sameness
// is the requirement, so a shared component is the spec rather than premature abstraction.
//
// The BFF handlers are the deliberate inverse (D5): Square and Clover OAuth genuinely
// differ, so those stay duplicated. Abstracting there would hide real behaviour; abstracting
// here prevents invented behaviour.

// One rail entry. Mirrors RailStep, restated so a vendor definition does not import a
// presentational type.
export type JourneyStepMeta = {
  title: string
  desc: string
}

// A GATE performs work and only then advances: it owns the single accent forward action,
// and the shell renders exactly one per panel.
export type GateStep = {
  kind: 'gate'
  meta: JourneyStepMeta
  body: ReactNode
  action: {
    label: string
    // Shown in place of `label` while running; the control is disabled throughout.
    runningLabel: string
    running: boolean
    // Additional reasons the action cannot proceed yet (an unmade choice, say).
    disabled?: boolean
    onAct: () => void
  }
}

// A SIGNPOST verifies nothing and writes nothing. It offers one or more doors, all of which
// lead onward; at most one is the accent action. Used where a precondition exists that we
// genuinely cannot check - see the Clover install step, where we do not know the merchant
// yet and so cannot ask the vendor anything.
export type SignpostStep = {
  kind: 'signpost'
  meta: JourneyStepMeta
  body: ReactNode
  actions: {
    label: string
    onAct: () => void
    // Exactly one action per signpost may be the accent; the shell does not enforce
    // "exactly one" at the type level, but renders at most the first as accent.
    accent?: boolean
    // An outbound link to a vendor property rather than an in-journey move.
    external?: boolean
  }[]
}

// A TERMINAL step has no forward action. It states the outcome and offers where to go next
// as secondary links.
export type TerminalStep = {
  kind: 'terminal'
  meta: JourneyStepMeta
  body: ReactNode
  links: { label: string; to: string }[]
}

export type JourneyStep = GateStep | SignpostStep | TerminalStep

export type JourneyDefinition = {
  // Rendered as "Connect {vendorName}" in the page head.
  vendorName: string
  steps: JourneyStep[]
  // The current step index and the shell's means of moving between them. Held by the vendor
  // because the vendor decides when work has succeeded; the shell only renders the rail and
  // wires backward jumps.
  step: number
  onJump: (index: number) => void
  // A single error line, already phrased for a client (D8): what happened and what to do,
  // one sentence, no error codes, no first person. null when there is nothing to say.
  error: string | null
  // The re-entry note, shown above the panel body when a prior run had already registered
  // everything. Shell-owned wording is impossible here (it names what was registered), so
  // the vendor supplies the sentence and the shell owns the presentation.
  note?: string | null
}
