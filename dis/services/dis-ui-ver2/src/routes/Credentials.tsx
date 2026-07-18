import { PremiumLock } from '../components/PremiumLock'

// Credentials & Secrets — integration credentials with rotation and expiry status. PREMIUM
// feature, lock TREATMENT B: the lock REPLACES the content. Only the H1 renders, with the
// premium-lock message below it — no subtitle, no note, no empty state, and no data path (this
// surface mounts nothing that fetches).
export function Credentials() {
  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Credentials &amp; Secrets</h1>
        </div>
      </div>
      <PremiumLock title="Credentials & Secrets is a premium feature" variant="replace" />
    </>
  )
}
