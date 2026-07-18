// Honest "pending backend" state. Some surfaces are L1: their backend route does not
// exist on the server yet, so their data clients are fixture-only and THROW in real
// mode. In real mode those surfaces render THIS instead of firing a doomed getter —
// an honest "pending its backend" message rather than an error banner or a misleading
// empty state. Sibling to EmptyState/ErrorState/LoadingState; uses the same .empty
// vocabulary so it reads consistently with Data Pipelines' pending markers.
export function PendingState({ title, message }: { title: string; message: string }) {
  return (
    <div className="empty">
      <h4>{title}</h4>
      <div>{message}</div>
    </div>
  )
}
