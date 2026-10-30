import { useState, type DragEvent } from 'react'
import { InboxOutlined, PaperClipOutlined } from '@ant-design/icons'

const size = (bytes: number) => bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`

/** A click-or-drop area around a native file input (kept for accessibility and resumable uploads). */
export default function FilePickField({ label, file, disabled, hint, onChange }: { label: string; file: File | null; disabled?: boolean; hint?: string; onChange: (file: File | null) => void }) {
  const [over, setOver] = useState(false)
  const drop = (event: DragEvent) => { event.preventDefault(); setOver(false); if (!disabled) onChange(event.dataTransfer.files?.[0] ?? null) }
  return <label className={`file-pick${over ? ' is-over' : ''}${disabled ? ' is-disabled' : ''}${file ? ' has-file' : ''}`}
    onDragOver={event => { event.preventDefault(); if (!disabled) setOver(true) }} onDragLeave={() => setOver(false)} onDrop={drop}>
    <input type="file" className="file-pick-input" aria-label={label} disabled={disabled} onChange={event => onChange(event.target.files?.[0] ?? null)} />
    {file ? <span className="file-pick-chosen"><PaperClipOutlined aria-hidden /><strong>{file.name}</strong><small>{size(file.size)} · 点击可更换</small></span>
      : <span className="file-pick-empty"><InboxOutlined aria-hidden /><strong>点击选择文件，或拖到这里</strong>{hint && <small>{hint}</small>}</span>}
  </label>
}
