import { useRef, useState } from 'react'

import { formatBytes } from '../lib/format-bytes'
import { Label } from './ui/label'

// Shared CSV dropzone with upload feedback, ported from dis-ui (same behavior/API) but reskinned
// to v2's vocabulary and WITHOUT an icon lib (v2 rule; dis-ui used lucide). States: EMPTY
// (dashed browse/drop prompt, real drag-and-drop wired), SELECTED (file card + Remove/Replace),
// BUSY (role=status label; no fake progress bar - fetch has no byte progress). The busy LABEL is
// the caller's responsibility so it stays accurate ("Analyzing ..." vs "Uploading ...").
type FileDropzoneProps = {
  id: string
  label: string
  file: File | null
  onSelect: (file: File | null) => void
  accept?: string
  hint?: string
  rowCount?: number | null
  busy?: boolean
  busyLabel?: string
  disabled?: boolean
  fileInputLabel?: string
}

export function FileDropzone({
  id,
  label,
  file,
  onSelect,
  accept,
  hint,
  rowCount = null,
  busy = false,
  busyLabel,
  disabled = false,
  fileInputLabel = 'CSV file',
}: FileDropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragActive, setDragActive] = useState(false)
  const locked = busy || disabled

  function pickFromDrop(dropped: FileList | null): void {
    const next = dropped?.[0] ?? null
    if (next !== null) onSelect(next)
  }
  function remove(): void {
    onSelect(null)
    if (inputRef.current !== null) inputRef.current.value = ''
  }

  const dropHandlers = {
    onDragOver: (e: React.DragEvent) => {
      if (locked) return
      e.preventDefault()
      setDragActive(true)
    },
    onDragLeave: () => setDragActive(false),
    onDrop: (e: React.DragEvent) => {
      if (locked) return
      e.preventDefault()
      setDragActive(false)
      pickFromDrop(e.dataTransfer.files)
    },
  }

  return (
    <div>
      <Label htmlFor={id}>{label}</Label>
      <input
        ref={inputRef}
        id={id}
        type="file"
        accept={accept}
        aria-label={fileInputLabel}
        disabled={locked}
        onChange={(e) => onSelect(e.target.files?.[0] ?? null)}
        style={{ position: 'absolute', width: 1, height: 1, padding: 0, margin: -1, overflow: 'hidden', clip: 'rect(0 0 0 0)', border: 0 }}
      />

      {busy ? (
        <div role="status" className="empty" style={{ padding: 20 }}>
          {busyLabel ?? 'Working...'}
        </div>
      ) : file === null ? (
        <label htmlFor={id} {...dropHandlers} className="empty" style={{ cursor: 'pointer', display: 'block', background: dragActive ? 'var(--surface-2)' : undefined }}>
          <h4>Drag and drop or browse</h4>
          {hint !== undefined ? <div>{hint}</div> : null}
        </label>
      ) : (
        <div {...dropHandlers} className="card" style={{ padding: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div className="pri-name" style={{ wordBreak: 'break-all' }}>
                {file.name}
              </div>
              <div className="mono" style={{ fontSize: 12, color: 'var(--text-3)' }}>
                {formatBytes(file.size)}
                {rowCount !== null ? ` · ${rowCount} rows` : ''}
              </div>
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              <button type="button" className="btn sm" onClick={() => inputRef.current?.click()}>
                Replace
              </button>
              <button type="button" className="btn sm danger" onClick={remove}>
                Remove
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
