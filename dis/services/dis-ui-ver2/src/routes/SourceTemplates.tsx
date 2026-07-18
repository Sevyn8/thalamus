import { Link, useNavigate } from 'react-router'

import { useAuth } from '../auth/useAuth'
import { useMappingTemplates } from '../lib/dis-ui-server/mapping-templates'

// Mapping Templates list surface, styled to the DIS V2 mockups (pagehead + card + .tbl).
// Renders the live lineage summaries from GET /api/v1/mapping-templates (RLS-scoped
// server-side). Each row links to the template detail.
export function SourceTemplates() {
  const { snapshot } = useAuth()
  const navigate = useNavigate()
  const query = useMappingTemplates(snapshot, null)

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Data Ingestion Templates</h1>
        </div>
      </div>

      {query.isPending ? <div className="empty">Loading templates…</div> : null}
      {query.isError ? (
        <div className="failbox" role="alert">
          Could not load templates: {query.error.message}
        </div>
      ) : null}

      {query.data !== undefined ? (
        query.data.length === 0 ? (
          <div className="empty">
            <h4>No mapping templates</h4>
            <div>Nothing in scope for this tenant yet.</div>
          </div>
        ) : (
          <div className="card">
            <div className="hd">
              <h3>Templates</h3>
              <span className="badge b-mut">{query.data.length}</span>
            </div>
            <div style={{ overflow: 'auto' }}>
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Template</th>
                    <th>Source</th>
                    <th>Type</th>
                    <th>Active</th>
                    <th>Versions</th>
                  </tr>
                </thead>
                <tbody>
                  {query.data.map((t) => (
                    // Whole-row navigation (Item 3): mouse click anywhere on the row navigates. The
                    // inner <Link> stays as the real href (middle-click / open-in-new-tab) AND the
                    // keyboard focus stop — so the row carries NO tabIndex/onKeyDown (that would
                    // double the tab stop for the same action).
                    <tr
                      className="click"
                      key={t.template_id}
                      onClick={() => navigate(`/templates/${t.template_id}`)}
                    >
                      <td>
                        <Link className="pri-name" to={`/templates/${t.template_id}`}>
                          {t.template_name}
                        </Link>
                      </td>
                      <td className="id">{t.source_id}</td>
                      <td>
                        <span className="badge b-info">{t.template_type}</span>
                      </td>
                      <td>
                        {t.active_version === null ? (
                          <span className="badge b-mut">none</span>
                        ) : (
                          <span className="badge b-ok">
                            <span className="dot d-ok" />v{t.active_version}
                          </span>
                        )}
                      </td>
                      <td className="mono">{t.versions_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )
      ) : null}
    </>
  )
}
