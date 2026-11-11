import { useRef, useState } from 'react'
import { Alert, Button, Modal, message } from 'antd'
import { UploadOutlined } from '@ant-design/icons'
import { api, errMsg } from '../api/client'
import type { ImportResult } from '../api/types'

/** Pick an Excel file, see exactly what it would add, then confirm. Nothing is written before that. */
export default function ImportModal({ open, title, url, hint, onClose, onDone }: {
  open: boolean; title: string; url: string; hint?: string; onClose: () => void; onDone: () => void
}) {
  const input = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<ImportResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [added, setAdded] = useState<string[]>([])
  const reset = () => { setFile(null); setPreview(null); setAdded([]) }
  const send = async (chosen: File, dry: boolean) => {
    setBusy(true)
    try {
      const form = new FormData()
      form.append('file', chosen)
      const { data } = await api.post<ImportResult>(`${url}?preview=${dry}`, form, { timeout: 120000 })
      if (dry) { setFile(chosen); setPreview(data) } else {
        message.success(data.counts.length ? data.counts.map((item) => `${item.label} ${item.count}`).join('，') : '没有需要导入的新内容')
        reset(); onDone(); onClose()
      }
    } catch (failure) {
      message.error(errMsg(failure))
    } finally {
      setBusy(false)
    }
  }
  const addModels = async () => {
    for (const name of preview?.unknown_models ?? []) {
      if (added.includes(name)) continue
      try { await api.post('/vehicle-types', { name }); setAdded((current) => [...current, name]) } catch (failure) { message.error(errMsg(failure)); return }
    }
    message.success('已加进车型库')
  }
  const unknown = (preview?.unknown_models ?? []).filter((name) => !added.includes(name))
  return <Modal open={open} title={title} onCancel={() => { reset(); onClose() }} destroyOnClose
    footer={preview ? [
      <Button key="again" onClick={reset}>换一个文件</Button>,
      <Button key="ok" type="primary" loading={busy} disabled={!preview.counts.some((item) => item.label.startsWith('新增') || item.label.startsWith('补全'))} onClick={() => file && void send(file, false)}>确认导入</Button>,
    ] : null}>
    {!preview && <>
      {hint && <p style={{ color: 'var(--agv-text-secondary)' }}>{hint}</p>}
      <Button icon={<UploadOutlined />} loading={busy} onClick={() => input.current?.click()}>选择 Excel 文件</Button>
      <input ref={input} type="file" hidden accept=".xlsx" aria-label="选择 Excel 文件" onChange={(event) => { const chosen = event.target.files?.[0]; event.target.value = ''; if (chosen) void send(chosen, true) }} />
    </>}
    {preview && <div aria-label="导入预览">
      <p><b>{file?.name}</b> 导入后会：</p>
      {preview.counts.length === 0 && <p>没有需要导入的新内容。</p>}
      <ul>{preview.counts.map((item) => <li key={item.label}>{item.label} <b>{item.count}</b></li>)}</ul>
      {preview.problem_count > 0 && <Alert type="warning" showIcon message={`有 ${preview.problem_count} 行读不了，会被跳过`}
        description={<ul style={{ margin: 0, paddingLeft: 18 }}>{preview.problems.map((problem) => <li key={problem}>{problem}</li>)}</ul>} />}
      {unknown.length > 0 && <Alert style={{ marginTop: 12 }} type="info" showIcon message={`车型库里还没有：${unknown.join('、')}`}
        action={<Button size="small" onClick={() => void addModels()}>加进车型库</Button>} />}
    </div>}
  </Modal>
}
