// Mockup steprail (connect-source.html): a vertical numbered rail with per-step title + blurb.
// Completed steps show a check glyph (no icon lib); the active step is highlighted. Steps before
// the current index are jump-navigable (Back); future steps are not.
export type RailStep = { title: string; desc: string }

export function StepRail({
  steps,
  current,
  onJump,
}: {
  steps: RailStep[]
  current: number
  onJump: (index: number) => void
}) {
  return (
    <nav className="steprail" aria-label="Progress">
      {steps.map((s, i) => {
        const state = i < current ? 'done' : i === current ? 'on' : ''
        const clickable = i < current
        return (
          <button
            key={s.title}
            type="button"
            className={`st ${state}`}
            aria-current={i === current ? 'step' : undefined}
            disabled={!clickable && i !== current}
            onClick={() => clickable && onJump(i)}
          >
            <div className="n">{i < current ? '✓' : i + 1}</div>
            <div>
              <div className="h">{s.title}</div>
              <div className="d">{s.desc}</div>
            </div>
          </button>
        )
      })}
    </nav>
  )
}
