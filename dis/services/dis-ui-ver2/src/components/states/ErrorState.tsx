// Reusable error state, v2 vocabulary (.failbox). role=alert so it is announced. Mirrors
// dis-ui's ErrorState API (message + optional onRetry); no icon lib (v2 rule).
export function ErrorState({
  message = 'Something went wrong.',
  onRetry,
}: {
  message?: string
  onRetry?: () => void
}) {
  return (
    <div role="alert" className="failbox">
      <div>{message}</div>
      {onRetry !== undefined ? (
        <button type="button" className="btn sm" style={{ marginTop: 10 }} onClick={onRetry}>
          Retry
        </button>
      ) : null}
    </div>
  )
}
