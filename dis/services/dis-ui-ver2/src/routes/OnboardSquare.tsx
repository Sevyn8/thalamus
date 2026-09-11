import { useState } from 'react'

import { useAuth } from '../auth/useAuth'
import {
  getConnectorHealth,
  type ConnectorHealthRow,
} from '../lib/dis-ui-server/connector-health'
import {
  createMappingTemplate,
  type MappingColumn,
} from '../lib/dis-ui-server/mapping-templates'
import { createSourceIfAbsent } from '../lib/dis-ui-server/sources'

// Onboard Square. ONE clickable screen that PROVISIONS the Square
// api-source + an ACTIVE snapshot template (create-as-ACTIVE) through the REAL BFF
// (POST /sources, POST /mapping-templates) and then VIEWS connector health
// (GET /connector-health). It does NOT fire a pull: the pull stays CLI-triggered (the spine
// transport). "Clickable" here means provisions + views, nothing more.
//
// EQUIVALENCE (the crux): the source + template posted here produce the SAME active config
// state as the spine's direct-DB provisioning.py. The source is channel='api', store_id='W-001';
// the template is template_type='snapshot' with one column per connector SNAPSHOT_HEADER field
// (identity src->dest, decimal separator on the two numeric columns). The BFF derives the
// mapping_rules from those columns via translate_columns_to_mapping_rules, which is asserted
// byte-equal to provisioning.snapshot_mapping_rules() by the Python drift guard
// (connectors/thalamus-square/tests/unit/test_provisioning_equivalence.py).

const SOURCE_ID = 'square_pos_v2'
const STORE_CODE = 'W-001'
const TEMPLATE_NAME = 'square snapshot'

// One column per SNAPSHOT_HEADER field (thalamus_square.mapping.SNAPSHOT_HEADER), in order.
// Identity src->dest; the two numeric columns carry a decimal separator so the BFF emits a
// parse_decimal normalize + a decimal cast. This list is the UI half of the equivalence proof.
const SNAPSHOT_COLUMNS: MappingColumn[] = [
  { src_key: 'sku_id', dest_key: 'sku_id' },
  { src_key: 'product_name', dest_key: 'product_name' },
  { src_key: 'product_description', dest_key: 'product_description' },
  { src_key: 'product_category', dest_key: 'product_category' },
  { src_key: 'barcode', dest_key: 'barcode' },
  { src_key: 'current_retail_price', dest_key: 'current_retail_price', src_decimal_separator: '.' },
  { src_key: 'currency', dest_key: 'currency' },
  { src_key: 'stock_qty', dest_key: 'stock_qty', src_decimal_separator: '.' },
]

type Phase = 'idle' | 'running' | 'done' | 'error'

type Result = {
  sourceCreated: boolean
  templateId: string
  health: ConnectorHealthRow[]
}

export function OnboardSquare() {
  const { snapshot } = useAuth()
  const [phase, setPhase] = useState<Phase>('idle')
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<Result | null>(null)

  async function provision(): Promise<void> {
    setPhase('running')
    setError(null)
    setResult(null)
    try {
      // 1) Register the api source (tolerate a 409: a prior run may have created it).
      const sourceCreated = await createSourceIfAbsent({
        source_id: SOURCE_ID,
        display_name: 'Square POS (sandbox)',
        channel: 'api',
        store_id: STORE_CODE,
      })
      // 2) Create the ACTIVE snapshot template (create-as-ACTIVE). Column-based body;
      //    the BFF derives + validates the mapping_rules server-side.
      const detail = await createMappingTemplate({
        source_id: SOURCE_ID,
        template_name: TEMPLATE_NAME,
        template_type: 'snapshot',
        columns: SNAPSHOT_COLUMNS,
      })
      // 3) View connector health (no pull is fired here).
      const health = await getConnectorHealth()
      setResult({
        sourceCreated,
        templateId: detail.template_id,
        health: health.items.filter((row) => row.source_id === SOURCE_ID),
      })
      setPhase('done')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Provisioning failed')
      setPhase('error')
    }
  }

  return (
    <section className="mx-auto mt-10 max-w-2xl px-4">
      <div className="warnbox" role="note" style={{ marginBottom: 12 }}>
        <b>DEV UTILITY</b> — provisioning parity tool (asserts UI-provisioned config equals the
        spine's). The customer journey is <span className="font-mono">/connect/square</span>.
      </div>
      <h1 className="mb-1 text-2xl font-semibold">Onboard Square</h1>
      <p className="mb-4 text-sm text-gray-500">
        Provisions the Square api-source and an ACTIVE snapshot template for {STORE_CODE}, then
        shows connector health. Does not run a pull - the offline pull is CLI-triggered.
      </p>

      <dl className="mb-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        <dt className="text-gray-500">Tenant</dt>
        <dd className="font-mono">{snapshot?.tenantId ?? '-'}</dd>
        <dt className="text-gray-500">Source</dt>
        <dd className="font-mono">{SOURCE_ID}</dd>
        <dt className="text-gray-500">Store</dt>
        <dd className="font-mono">{STORE_CODE}</dd>
      </dl>

      <button
        type="button"
        onClick={() => void provision()}
        disabled={phase === 'running'}
        className="rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-700 disabled:opacity-50"
      >
        {phase === 'running' ? 'Provisioning...' : 'Provision Square (snapshot)'}
      </button>

      {error !== null ? (
        <p role="alert" className="mt-3 text-sm text-red-600">
          {error}
        </p>
      ) : null}

      {result !== null ? (
        <div className="mt-6">
          <p className="text-sm text-gray-700">
            Source {result.sourceCreated ? 'created' : 'already existed'}. Template{' '}
            <span className="font-mono">{result.templateId}</span> is ACTIVE.
          </p>
          <h2 className="mt-4 mb-2 text-base font-semibold">Connector health</h2>
          {result.health.length === 0 ? (
            <p className="text-sm text-gray-500">No connector-health row yet for {SOURCE_ID}.</p>
          ) : (
            <table className="w-full border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-gray-300 text-gray-500">
                  <th className="py-1 pr-4 font-medium">Source</th>
                  <th className="py-1 pr-4 font-medium">Channel</th>
                  <th className="py-1 pr-4 font-medium">Status</th>
                  <th className="py-1 pr-4 font-medium">Last seen</th>
                </tr>
              </thead>
              <tbody>
                {result.health.map((row) => (
                  <tr key={row.source_id} className="border-b border-gray-100">
                    <td className="py-1 pr-4 font-mono">{row.source_id}</td>
                    <td className="py-1 pr-4">{row.channel ?? '-'}</td>
                    <td className="py-1 pr-4">{row.status}</td>
                    <td className="py-1 pr-4">{row.last_seen_at ?? '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ) : null}
    </section>
  )
}
