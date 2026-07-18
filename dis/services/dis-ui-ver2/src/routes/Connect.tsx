import { useState } from 'react'

import { CsvWizard } from './connect/CsvWizard'
import { PosWizard } from './connect/PosWizard'

// Connect a data source (mockup connect-source.html). Step 1 "Source & method" offers six method
// tiles (CSV first per spec). CSV -> the real 7-step wizard; Native/POS connector -> the 9-step
// designed walkthrough (stubbed, honesty-marked); the other four methods -> a styled
// "not built yet" state (no wizard). Surface shape follows the mockup, not dis-ui.

type Method = 'csv' | 'pos' | 'api' | 'webhook' | 'sftp' | 'ipaas'

const TILES: { key: Method; glyph: string; title: string; desc: string; kind: 'csv' | 'pos' | 'unbuilt' }[] = [
  { key: 'csv', glyph: '▦', title: 'Manual CSV', desc: 'Upload files on demand', kind: 'csv' },
  { key: 'pos', glyph: '◇', title: 'Native connector', desc: 'OAuth sign-in to a known vendor (Clover / Square / Shopify)', kind: 'pos' },
  { key: 'api', glyph: '⇄', title: 'API pull', desc: 'Poll a REST endpoint on a schedule', kind: 'unbuilt' },
  { key: 'webhook', glyph: '⇥', title: 'Webhook push', desc: 'Receive events at a generated endpoint', kind: 'unbuilt' },
  { key: 'sftp', glyph: '⇩', title: 'SFTP', desc: 'Scheduled file drop', kind: 'unbuilt' },
  { key: 'ipaas', glyph: '⌘', title: 'iPaaS / custom', desc: 'Delivered via Workato, Zapier, etc.', kind: 'unbuilt' },
]

export function Connect() {
  const [method, setMethod] = useState<Method | null>(null)
  const tile = TILES.find((t) => t.key === method)

  if (tile?.kind === 'csv') return withHead(<CsvWizard onBack={() => setMethod(null)} />)
  if (tile?.kind === 'pos') return withHead(<PosWizard onBack={() => setMethod(null)} />)
  if (tile?.kind === 'unbuilt') {
    return withHead(
      <>
        <button type="button" className="btn" style={{ marginBottom: 14 }} onClick={() => setMethod(null)}>
          ← Back
        </button>
        <div className="empty">
          <h4>{tile.title} isn’t available yet</h4>
        </div>
      </>,
    )
  }

  return withHead(
    <>
      <div className="choicegrid">
        {TILES.map((t) => (
          <button key={t.key} type="button" className="choice" onClick={() => setMethod(t.key)}>
            {t.key !== 'csv' && <span className="badge b-mut choice__soon">Coming soon</span>}
            <div className="ic">{t.glyph}</div>
            <div className="t">{t.title}</div>
            <div className="d">{t.desc}</div>
          </button>
        ))}
      </div>
    </>,
  )
}

function withHead(body: React.ReactNode) {
  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Connect a Data Source</h1>
        </div>
      </div>
      {body}
    </>
  )
}
