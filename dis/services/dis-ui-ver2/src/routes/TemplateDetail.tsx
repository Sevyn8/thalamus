import { useState } from 'react'
import { Link, useParams } from 'react-router'

import { useAuth } from '../auth/useAuth'
import { DisUiServerHttpError } from '../lib/dis-ui-server/client'
import { useTemplateMappingFieldsForType } from '../lib/dis-ui-server/mapping-fields'
import type { CatalogField } from '../lib/dis-ui-server/mapping-fields'
import type { MappingTemplateVersion, TemplateStatus } from '../lib/dis-ui-server/mapping-templates'
import {
  activeTemplateVersion,
  patchMappingTemplate,
  useMappingTemplate,
} from '../lib/dis-ui-server/mapping-templates'
import { useSources } from '../lib/dis-ui-server/sources'

// Mapping Template detail — mockup-faithful (template-detail.html): KPI row + "Versions &
// lifecycle" card + "Mappings & rules" card with a business/technical view toggle. REAL data
// (mode-aware): GET /api/v1/mapping-templates/{id} (versions[].mapping_rules) + GET
// /api/v1/template-mapping-fields (catalog: business label + mandatory→class). Fields the
// backend does not carry (per-version change note; per-field sample value) render "—", never
// fabricated. The existing real GET path (first wired surface) is preserved.

const STATUS_BADGE: Record<TemplateStatus, string> = {
  active: 'b-ok',
  staged: 'b-warn',
  draft: 'b-mut',
  deprecated: 'b-fail',
}

// One row of the Mappings & rules table, assembled from mapping_rules + catalog.
type RuleRow = {
  sourceField: string
  destKey: string
  businessLabel: string
  mandatory: boolean | null
  transform: string
  ignored: boolean
}

function buildRules(
  version: MappingTemplateVersion | null,
  catalog: CatalogField[],
): RuleRow[] {
  if (version === null) return []
  const byKey = new Map(catalog.map((c) => [c.key, c]))
  const rules = version.mapping_rules
  return Object.entries(rules.rename).map(([src, dest]) => {
    const cat = byKey.get(dest)
    const ops = [
      ...(rules.normalize[dest] ?? []).map((o) => o.op),
      ...(rules.cast[dest] !== undefined ? [`cast:${rules.cast[dest].type}`] : []),
      ...(rules.derive[dest] ?? []).map((o) => `derive:${o.op}`),
    ]
    return {
      sourceField: src,
      destKey: dest,
      businessLabel: cat?.display_name ?? dest,
      mandatory: cat?.mandatory ?? null,
      transform: ops.join(', ') || '—',
      ignored: dest === '__ignore__',
    }
  })
}

export function TemplateDetail() {
  const { snapshot } = useAuth()
  const { templateId } = useParams<{ templateId: string }>()
  const query = useMappingTemplate(snapshot, templateId ?? null)
  const d = query.data
  const fields = useTemplateMappingFieldsForType(d?.template_type ?? null)
  const [view, setView] = useState<'business' | 'technical'>('business')
  // Inline rename (backend already supports PATCH template_name; this is the missing UI surface).
  const [editingName, setEditingName] = useState(false)
  const [nameDraft, setNameDraft] = useState('')
  const [renamePhase, setRenamePhase] = useState<'idle' | 'saving'>('idle')
  const [renameError, setRenameError] = useState<string | null>(null)

  const active = d !== undefined ? activeTemplateVersion(d) : null
  const rules = buildRules(active, fields.data ?? [])

  // Upload guard (Phase B, D112): look up this template's source channel from GET /sources and
  // hide Upload ONLY for explicitly push/pull automated sources (api/reverse_api) — you don't
  // manually upload to those. A NULL/un-inferred channel, or a source not found in /sources,
  // is treated as NOT push/pull (allow upload), so file/csv/erp/unknown sources never regress.
  // Replaces the old reliance on the wire-defaulted `ingestion_mode ?? 'file'`.
  const sources = useSources(snapshot)
  const sourceChannel =
    d !== undefined
      ? ((sources.data ?? []).find((s) => s.source_id === d.source_id)?.channel ?? null)
      : null
  const isPushPull = sourceChannel === 'api' || sourceChannel === 'reverse_api'

  // Acted-for tenant for the rename write. The template wire shape carries no tenant_id, so a
  // PLATFORM caller derives it from the template's source (same /sources read the upload guard
  // uses above). A TENANT caller never sends it (the server pins its own tenant; naming one is a
  // 403). If a PLATFORM caller's source is not in the visible set, actedFor is undefined and the
  // write surfaces the server's 403 inline rather than guessing a tenant.
  const isPlatform = snapshot?.userType === 'PLATFORM'
  const actedFor =
    isPlatform && d !== undefined
      ? ((sources.data ?? []).find((s) => s.source_id === d.source_id)?.tenant_id ?? undefined)
      : undefined

  function startRename(): void {
    if (d === undefined) return
    setNameDraft(d.template_name)
    setRenameError(null)
    setEditingName(true)
  }

  function cancelRename(): void {
    setEditingName(false)
    setRenameError(null)
  }

  async function saveRename(): Promise<void> {
    if (d === undefined) return
    const next = nameDraft.trim()
    if (next === '' || next === d.template_name) {
      setEditingName(false)
      return
    }
    setRenamePhase('saving')
    setRenameError(null)
    try {
      await patchMappingTemplate(d.template_id, {
        template_name: next,
        acting_for_tenant_id: actedFor,
      })
      setEditingName(false)
      setRenamePhase('idle')
      await query.refetch()
    } catch (err) {
      setRenamePhase('idle')
      if (err instanceof DisUiServerHttpError && err.status === 409) {
        setRenameError(
          err.message !== ''
            ? err.message
            : 'That name is already used by another template of this source.',
        )
      } else {
        setRenameError(err instanceof Error ? err.message : 'Rename failed')
      }
    }
  }

  return (
    <>
      <div className="pagehead">
        <div>
          <div style={{ marginBottom: 6 }}>
            <Link to="/templates" className="mono" style={{ fontSize: 12 }}>
              &larr; Data Ingestion Templates
            </Link>
          </div>
          {d === undefined ? (
            <h1>Mapping Template</h1>
          ) : editingName ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <input
                aria-label="Template name"
                value={nameDraft}
                onChange={(e) => setNameDraft(e.target.value)}
                disabled={renamePhase === 'saving'}
              />
              <button
                type="button"
                className="btn pri"
                disabled={renamePhase === 'saving'}
                onClick={() => void saveRename()}
              >
                {renamePhase === 'saving' ? 'Saving…' : 'Save'}
              </button>
              <button
                type="button"
                className="btn"
                disabled={renamePhase === 'saving'}
                onClick={cancelRename}
              >
                Cancel
              </button>
            </div>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <h1>{d.template_name}</h1>
              <button
                type="button"
                className="btn"
                aria-label="Rename template"
                onClick={startRename}
              >
                Rename
              </button>
            </div>
          )}
          {renameError !== null ? (
            <p role="alert" className="failbox" style={{ marginTop: 6 }}>
              {renameError}
            </p>
          ) : null}
          {d !== undefined ? (
            <div className="sub">
              <span className="id">{d.source_id}</span> · {d.template_type}
            </div>
          ) : null}
        </div>
        {d !== undefined && !isPushPull && d.active_version !== null ? (
          <div className="actions">
            <Link className="btn pri" to={`/templates/${d.template_id}/upload`}>
              Upload data
            </Link>
          </div>
        ) : null}
      </div>

      {query.isPending ? <div className="empty">Loading template…</div> : null}
      {query.isError ? (
        <div className="failbox" role="alert">
          Could not load template: {query.error.message}
        </div>
      ) : null}

      {d !== undefined ? (
        <>
          <div className="grid g4 gap12" style={{ marginBottom: 16 }}>
            <div className="kpi">
              <div className="top">Latest</div>
              <div className="val">v{d.latest_version}</div>
            </div>
            <div className="kpi">
              <div className="top">Active</div>
              <div className="val">{d.active_version === null ? '—' : `v${d.active_version}`}</div>
            </div>
            <div className="kpi">
              <div className="top">Staged</div>
              <div className="val">{d.staged_version === null ? '—' : `v${d.staged_version}`}</div>
            </div>
            <div className="kpi">
              <div className="top">Draft</div>
              <div className="val">{d.draft_version === null ? '—' : `v${d.draft_version}`}</div>
            </div>
          </div>

          <div className="grid g2" style={{ marginBottom: 16 }}>
            {/* Versions & lifecycle (mockup columns: Version·State·By·When·Change) */}
            <div className="card">
              <div className="hd">
                <h3>Versions &amp; lifecycle</h3>
                <span className="badge b-mut">{d.versions_count}</span>
              </div>
              <div style={{ overflow: 'auto' }}>
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Version</th>
                      <th>State</th>
                      <th>By</th>
                      <th>When</th>
                      <th>Change</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.versions.map((v) => (
                      <tr key={v.mapping_version_id}>
                        <td className="pri-name">v{v.version}</td>
                        <td>
                          <span className={`badge ${STATUS_BADGE[v.status]}`}>{v.status}</span>
                        </td>
                        <td className="id">{v.created_by_user_id ?? '—'}</td>
                        <td className="id">{new Date(v.created_at).toISOString().slice(0, 10)}</td>
                        <td className="id">—</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Mappings & rules (mockup: Class·Business label·Source field·Sample·Transform·Status)
                with a business/technical view toggle. From the ACTIVE version's mapping_rules +
                the catalog. Sample values are not carried by the backend -> "—". */}
            <div className="card">
              <div className="hd">
                <h3>Mappings &amp; rules</h3>
                <div className="actions">
                  <div className="segment">
                    <button
                      type="button"
                      className={view === 'business' ? 'on' : ''}
                      onClick={() => setView('business')}
                    >
                      Business
                    </button>
                    <button
                      type="button"
                      className={view === 'technical' ? 'on' : ''}
                      onClick={() => setView('technical')}
                    >
                      Technical
                    </button>
                  </div>
                </div>
              </div>
              {active === null ? (
                <div className="bd">
                  <div className="empty">No active version to show mappings for.</div>
                </div>
              ) : rules.length === 0 ? (
                <div className="bd">
                  <div className="empty">No field mappings in this version.</div>
                </div>
              ) : (
                <div style={{ overflow: 'auto' }}>
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th>Class</th>
                        <th>{view === 'business' ? 'Business label' : 'Canonical key'}</th>
                        <th>Source field</th>
                        <th>Sample</th>
                        <th>Transform</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rules.map((r) => (
                        <tr key={r.sourceField}>
                          <td>
                            {r.mandatory === null ? (
                              <span className="reqchip req-opt">—</span>
                            ) : r.mandatory ? (
                              <span className="reqchip req-req">required</span>
                            ) : (
                              <span className="reqchip req-opt">optional</span>
                            )}
                          </td>
                          <td className={view === 'technical' ? 'mono' : 'pri-name'}>
                            {view === 'business' ? r.businessLabel : r.destKey}
                          </td>
                          <td className="id">{r.sourceField}</td>
                          <td className="id">—</td>
                          <td className="mono">{r.transform}</td>
                          <td>
                            {r.ignored ? (
                              <span className="badge b-mut">ignored</span>
                            ) : (
                              <span className="badge b-ok">mapped</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        </>
      ) : null}
    </>
  )
}
