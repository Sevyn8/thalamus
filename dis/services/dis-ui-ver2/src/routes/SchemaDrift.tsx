import { PremiumLock } from '../components/PremiumLock'

// Schema Drift & Changes — the shadow rollout review (staged mapping vs the active version).
// PREMIUM feature, lock TREATMENT B: the lock REPLACES the content. Only the H1 renders, with the
// premium-lock message below it — no subtitle, no body, and NO data path (this surface mounts no
// shadow hooks, so no backend fetch fires).
export function SchemaDrift() {
  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Schema Drift &amp; Changes</h1>
        </div>
      </div>
      <PremiumLock title="Schema Drift is a premium feature" variant="replace" />
    </>
  )
}
