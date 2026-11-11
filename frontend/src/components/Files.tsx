import { useRef, useState, type DragEvent } from 'react'
import { message } from 'antd'
import { CloseOutlined, FileOutlined, PaperClipOutlined, PictureOutlined } from '@ant-design/icons'
import { api, errMsg, newId } from '../api/client'
import type { FileRow } from '../api/types'
import { day, fileSize } from '../utils/format'
import './Files.css'

const LONG_EDGE = 2000

/** Phone photos are several megabytes; shrink them before they travel over a site's network. */
export async function shrinkPhoto(file: File): Promise<File> {
  if (!/^image\/(jpeg|png|webp)$/.test(file.type) || file.size < 600 * 1024 || typeof createImageBitmap !== 'function') return file
  try {
    const bitmap = await createImageBitmap(file)
    const scale = Math.min(1, LONG_EDGE / Math.max(bitmap.width, bitmap.height))
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(bitmap.width * scale)
    canvas.height = Math.round(bitmap.height * scale)
    canvas.getContext('2d')!.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.82))
    if (!blob || blob.size >= file.size) return file
    return new File([blob], file.name.replace(/\.(png|webp|jpe?g)$/i, '') + '.jpg', { type: 'image/jpeg' })
  } catch {
    return file
  }
}

export async function uploadFiles(projectId: string, files: File[], ownerKind: FileRow['owner_kind'], ownerId: string | null): Promise<void> {
  for (const original of files) {
    const file = await shrinkPhoto(original)
    const form = new FormData()
    form.append('file', file)
    form.append('owner_kind', ownerKind)
    form.append('owner_id', ownerId ?? '')
    form.append('id', newId())
    await api.post(`/projects/${projectId}/files`, form, { timeout: 0 })
  }
}

/** The files of one row with a button (and a drop target) to add more. */
export default function Files({ projectId, files, ownerKind, ownerId, people, track, label = '上传', onChanged }: {
  projectId: string; files: FileRow[]; ownerKind: FileRow['owner_kind']; ownerId: string | null; people: Record<string, string>
  track: <R>(write: Promise<R>) => Promise<R>; label?: string; onChanged?: () => void
}) {
  const input = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [over, setOver] = useState(false)
  const send = async (list: File[]) => {
    if (!list.length || busy) return
    setBusy(true)
    try {
      await track(uploadFiles(projectId, list, ownerKind, ownerId))
      onChanged?.()
    } catch (failure) {
      message.error(errMsg(failure))
    } finally {
      setBusy(false)
    }
  }
  const remove = async (file: FileRow) => {
    try {
      await track(api.delete(`/files/${file.id}`))
      const key = `file-${file.id}`
      message.open({ key, type: 'success', duration: 6, content: <span>已删除　<a onClick={() => {
        message.destroy(key)
        void track(api.post(`/files/${file.id}/restore`)).catch((failure) => message.error(errMsg(failure)))
      }}>撤销</a></span> })
    } catch (failure) {
      message.error(errMsg(failure))
    }
  }
  const drop = (event: DragEvent) => {
    event.preventDefault()
    setOver(false)
    void send(Array.from(event.dataTransfer.files))
  }
  return <div className={`files${over ? ' is-over' : ''}`} onDragOver={(event) => { event.preventDefault(); setOver(true) }} onDragLeave={() => setOver(false)} onDrop={drop}>
    {files.map((file) => <span key={file.id} className="file-chip" title={`${fileSize(file.size)} · ${(file.created_by && people[file.created_by]) || ''} ${day(file.created_at)}`}>
      <a href={`/api/files/${file.id}`} target="_blank" rel="noreferrer">
        {file.mime.startsWith('image/') ? <PictureOutlined /> : <FileOutlined />}<span className="file-name">{file.filename}</span>
      </a>
      <button type="button" aria-label={`删除文件 ${file.filename}`} onClick={() => void remove(file)}><CloseOutlined /></button>
    </span>)}
    <button type="button" className="file-add" disabled={busy} onClick={() => input.current?.click()}><PaperClipOutlined />{busy ? '上传中…' : label}</button>
    <input ref={input} type="file" multiple hidden aria-label={label} onChange={(event) => { void send(Array.from(event.target.files ?? [])); event.target.value = '' }} />
  </div>
}
