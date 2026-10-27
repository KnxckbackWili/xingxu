import { useRef, useState } from 'react'
import { Select, Tooltip } from 'antd'
import { ExclamationCircleOutlined } from '@ant-design/icons'
import './quickControls.css'

interface Props {
  label: string
  value: string | null | undefined
  options: Array<{ value: string; label: string }>
  onSave: (value: string | undefined) => Promise<void>
  disabled?: boolean
  allowClear?: boolean
  placeholder?: string
  width?: number
}

/** Saves one field after selecting it; the confirmed value survives a failed request. */
export default function InlineSelect({ label, value, options, onSave, disabled, allowClear, placeholder, width = 120 }: Props) {
  const busy = useRef(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const save = async (next: string | undefined) => {
    if (disabled || busy.current || (next ?? null) === (value ?? null)) return
    busy.current = true; setSaving(true); setError('')
    try { await onSave(next) }
    catch (cause: any) {
      const detail = cause?.response?.data?.detail
      setError(typeof detail === 'string' ? detail : cause?.message || '保存失败，原值已保留，请重试')
    }
    finally { busy.current = false; setSaving(false) }
  }
  return <span className="inline-select" onClick={(event) => event.stopPropagation()}>
    <Select aria-label={label} size="small" value={value ?? undefined} options={options}
      disabled={disabled || saving} loading={saving} allowClear={allowClear} showSearch optionFilterProp="label"
      placeholder={placeholder} style={{ width }} onChange={save} />
    {error && <Tooltip title={error}><span role="alert" aria-label={`${label}保存失败：${error}`} className="inline-save-error"><ExclamationCircleOutlined /></span></Tooltip>}
  </span>
}
