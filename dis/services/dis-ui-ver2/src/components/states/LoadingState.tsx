// Reusable loading state, v2 vocabulary. role=status so it is announced/queryable, mirroring
// dis-ui's LoadingState API (label). An indeterminate CSS bar (pure @keyframes, NO icon lib per the
// v2 no-icon rule) signals active background work; the text label remains the honest, announced
// signal (the bar is aria-hidden so screen readers get the label, not the decoration).
export function LoadingState({ label = 'Loading...' }: { label?: string }) {
  return (
    <div role="status" className="loadingstate">
      <span className="loadingbar" aria-hidden="true">
        <i />
      </span>
      <span>{label}</span>
    </div>
  )
}
