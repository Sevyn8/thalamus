import { useState } from 'react'
import { Link, useParams } from 'react-router'

import { useAuth } from '../auth/useAuth'
import { FileDropzone } from '../components/FileDropzone'
import { EmptyState } from '../components/states/EmptyState'
import { ErrorState } from '../components/states/ErrorState'
import { LoadingState } from '../components/states/LoadingState'
import { Label } from '../components/ui/label'
import { Select } from '../components/ui/select'
import { DisUiServerHttpError } from '../lib/dis-ui-server/client'
import { uploadCsvWithSessionToken } from '../lib/dis-ui-server/csv-uploads'
import type { CsvUploadResult } from '../lib/dis-ui-server/csv-uploads'
import { activeTemplateVersion, useMappingTemplate } from '../lib/dis-ui-server/mapping-templates'
import { useStoresOnboarded } from '../lib/dis-ui-server/stores'

// CSV batch upload, ported from dis-ui's RecurringBatchUpload and reskinned to v2. Reached from
// the Mapping Template detail (dis-ui-faithful home). Guards mirror dis-ui EXACTLY: template
// loaded -> not api-mode -> active version -> ACTIVE store w/ store_code selected -> file. The
// POST is always-real (csv-uploads); the file bytes are genuinely sent (201 = received, mapped
// asynchronously through the template's active version).

// Map a dis-ui-server error to a message (contract 8.1 status + envelope code), mirroring dis-ui.
function uploadErrorMessage(err: unknown): string {
  if (err instanceof DisUiServerHttpError) {
    switch (err.status) {
      case 404:
        return 'Template or store not found.'
      case 409:
        return err.code === 'store_state_conflict'
          ? 'The selected store is not active.'
          : 'This template has no active version yet.'
      case 413:
        return 'File exceeds the 10 MB limit.'
      case 422: {
        const reason = typeof err.details.reason === 'string' ? ` (${err.details.reason})` : ''
        return `The file failed the structural check${reason}.`
      }
      case 503:
        return 'The upload service is temporarily unavailable; please retry.'
      default:
        return 'The upload could not be completed.'
    }
  }
  return 'The upload could not be completed.'
}

export function BatchUpload() {
  const { templateId } = useParams<{ templateId: string }>()
  const { snapshot } = useAuth()
  const detail = useMappingTemplate(snapshot, templateId ?? null)
  const stores = useStoresOnboarded(snapshot)

  const [file, setFile] = useState<File | null>(null)
  const [storeCode, setStoreCode] = useState('')
  const [result, setResult] = useState<CsvUploadResult | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const head = (
    <div className="pagehead">
      <div>
        <div style={{ marginBottom: 6 }}>
          <Link to={`/templates/${templateId ?? ''}`} className="mono" style={{ fontSize: 12 }}>
            &larr; Template
          </Link>
        </div>
        <h1>Upload Data</h1>
      </div>
    </div>
  )

  if (templateId === undefined) return <>{head}<EmptyState title="No template" message="No template id in the URL." /></>
  if (detail.isPending) return <>{head}<LoadingState label="Loading template…" /></>
  if (detail.isError || detail.data === undefined) return <>{head}<ErrorState message="Could not load this template." /></>

  const template = detail.data

  // api-mode guard (dis-ui FM1): connector sources sync automatically; no manual upload.
  if (template.ingestion_mode === 'api') {
    return (
      <>
        {head}
        <EmptyState
          title="Connected / syncing"
          message="This source syncs automatically through its connector. There is no manual upload; batches arrive over the connector."
        />
      </>
    )
  }

  const active = activeTemplateVersion(template)
  // The endpoint requires an ACTIVE store WITH a store_code (a non-active/code-less store 404/409s).
  const uploadableStores = (stores.data ?? []).filter(
    (s) => s.status === 'active' && s.store_code !== null,
  )

  // ingest needs an active version (dis-ui FM3): guard direct navigation too.
  if (active === null) {
    return (
      <>
        {head}
        <EmptyState
          title="No active version yet"
          message="This template has no active version yet. Activate a mapping before ingesting a batch."
        />
      </>
    )
  }

  async function confirmUpload(): Promise<void> {
    setSubmitError(null)
    if (file === null || storeCode === '') return
    setSubmitting(true)
    try {
      const uploaded = await uploadCsvWithSessionToken({
        file,
        templateId: template.template_id,
        storeCode,
      })
      setResult(uploaded)
    } catch (err) {
      setSubmitError(uploadErrorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      {head}
      <div className="card" style={{ maxWidth: 640 }}>
        <div className="hd">
          <h3>{template.template_name}</h3>
          <span className="badge b-info">{template.source_id}</span>
        </div>
        <div className="bd" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div className="note">
            Uploaded files are ingested asynchronously; mapping is applied after upload via the
            active version (v{active.version}), not instantly.
          </div>

          <div>
            <Label htmlFor="ingest-store">Store</Label>
            <Select
              id="ingest-store"
              aria-label="Store"
              value={storeCode}
              onChange={(e) => setStoreCode(e.target.value)}
            >
              <option value="">Select a store</option>
              {uploadableStores.map((s) => (
                <option key={s.store_id} value={s.store_code ?? ''}>
                  {s.name} ({s.store_code})
                </option>
              ))}
            </Select>
            {uploadableStores.length === 0 ? (
              <div className="field">
                <span className="hint">No active stores with a store code are available.</span>
              </div>
            ) : null}
          </div>

          <FileDropzone
            id="batch-csv-file"
            label="Batch CSV file"
            file={file}
            onSelect={setFile}
            accept=".csv"
            hint="CSV up to 10 MB"
            busy={submitting}
            busyLabel={file !== null ? `Uploading ${file.name}...` : undefined}
          />

          {submitError !== null ? (
            <div className="failbox" role="alert">
              {submitError}
            </div>
          ) : null}

          {result !== null ? (
            <div className="okbox" role="status">
              Uploaded {file?.name}. {result.row_count} rows received against{' '}
              {template.template_name}, ingested asynchronously through the active mapping version.
              Trace {result.trace_id}.
            </div>
          ) : (
            <div>
              <button
                type="button"
                className="btn pri"
                disabled={submitting || file === null || storeCode === ''}
                onClick={() => void confirmUpload()}
              >
                Upload and ingest
              </button>
            </div>
          )}
        </div>
      </div>
    </>
  )
}
