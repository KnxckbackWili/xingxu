import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, Button, Card, Checkbox, DatePicker, Drawer, Empty, Input, Popconfirm, Select, Space, Table, Tag, Typography } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import { externalSharesApi, SHARE_SCOPES, type ShareScope, type ExternalShare, type ShareOption, type ExternalAccess } from '../../../api/externalShares'
import { errMsg } from '../../../api/client'

const defaultScopes: ShareScope[] = ['project_progress', 'vehicle_progress']
export default function ExternalSharePanel({ projectId, enabled, onDirtyChange }: { projectId: string; enabled: boolean; onDirtyChange: (dirty: boolean) => void }) {
  const generation = useRef(0)
  const mutation = useRef(false)
  const [rows, setRows] = useState<ExternalShare[]>([])
  const [options, setOptions] = useState<ShareOption[]>([])
  const [scopes, setScopes] = useState<ShareScope[]>(defaultScopes)
  const [selected, setSelected] = useState<string[]>([])
  const [expiry, setExpiry] = useState<Dayjs | null>(() => dayjs().add(7, 'day'))
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [link, setLink] = useState('')
  const [logId, setLogId] = useState<string | null>(null)
  const [logs, setLogs] = useState<ExternalAccess[]>([])
  const [logError, setLogError] = useState('')
  const [logLoading, setLogLoading] = useState(false)
  const logSequence = useRef(0)
  const load = useCallback(async () => {
    const ticket = ++generation.current
    setLoading(true); setError('')
    try {
      const result = await externalSharesApi.list(projectId)
      if (ticket === generation.current) { setRows(result.shares); setOptions(result.document_options) }
    } catch (failure) { if (ticket === generation.current) { setRows([]); setOptions([]); setError(errMsg(failure)) } }
    finally { if (ticket === generation.current) setLoading(false) }
  }, [projectId])
  useEffect(() => {
    setLink(''); setRows([]); setOptions([]); setScopes(defaultScopes); setSelected([]); setExpiry(dayjs().add(7, 'day')); setLogId(null)
    mutation.current = false; setBusy(false); onDirtyChange(false)
    if (enabled) void load()
    return () => { generation.current++; logSequence.current++ }
  }, [projectId, enabled, load, onDirtyChange])
  const create = async () => {
    if (!enabled || loading || error || mutation.current || !expiry || !scopes.length || scopes.includes('selected_documents') && !selected.length) return
    const ticket = generation.current
    mutation.current = true; setBusy(true); setLink(''); setError('')
    try {
      const result = await externalSharesApi.create(projectId, { scopes, document_ids: scopes.includes('selected_documents') ? selected : [], expires_at: expiry.toISOString() })
      if (ticket !== generation.current) return
      // The raw secret exists only here and in the original recipient link.
      setLink(`${window.location.origin}/external#token=${encodeURIComponent(result.token)}`)
      const { token: _secret, ...safe } = result
      setRows(previous => [safe, ...previous]); onDirtyChange(false)
    } catch (failure) { if (ticket === generation.current) setError(`${errMsg(failure)}。如创建结果未确认，请先刷新列表核对；链接令牌无法找回，可撤销后重建。`) }
    finally { if (ticket === generation.current) { mutation.current = false; setBusy(false) } }
  }
  const revoke = async (row: ExternalShare) => {
    if (!enabled || mutation.current) return
    const ticket = generation.current
    mutation.current = true; setBusy(true); setError('')
    try {
      const updated = await externalSharesApi.revoke(projectId, row)
      if (ticket === generation.current) { setRows(previous => previous.map(item => item.id === row.id ? updated : item)); setLink('') }
    } catch (failure) { if (ticket === generation.current) setError(errMsg(failure)) }
    finally { if (ticket === generation.current) { mutation.current = false; setBusy(false) } }
  }
  const showLogs = async (id: string) => {
    const ticket = ++logSequence.current
    setLogId(id); setLogs([]); setLogError(''); setLogLoading(true)
    try { const result = await externalSharesApi.access(projectId, id); if (ticket === logSequence.current) setLogs(result) }
    catch (failure) { if (ticket === logSequence.current) setLogError(errMsg(failure)) }
    finally { if (ticket === logSequence.current) setLogLoading(false) }
  }
  if (!enabled) return <Alert type="info" message="仅当前项目负责人可管理外部查看，需要项目资料维护权限。" />
  return <Space direction="vertical" size={16} style={{ width: '100%' }}>
    <Alert type="info" showIcon message="默认只分享项目进度和车辆进度" description="保密资料和永不对外的资料始终不可外部读取。新增签单或交付资料范围时，将包含以后提交的符合范围的最新版本；指定资料只含所选期次，以后新期次不会自动加入。" />
    {error && <Alert type="error" showIcon message={error} action={<Button disabled={busy} onClick={() => void load()}>刷新核对</Button>} />}
    <Card title="创建只读分享" size="small">
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <div><Typography.Paragraph>选择内容范围</Typography.Paragraph><Checkbox.Group aria-label="分享内容范围" options={SHARE_SCOPES} value={scopes} disabled={busy || loading} onChange={values => { setScopes(values as ShareScope[]); onDirtyChange(true) }} /></div>
        {scopes.includes('selected_documents') && <Select aria-label="指定对外资料" mode="multiple" showSearch optionFilterProp="label" value={selected} disabled={busy || loading} onChange={values => { setSelected(values); onDirtyChange(true) }} placeholder="选择明确资料，保密内容不在候选中" style={{ width: '100%' }} options={options.map(row => ({ value: row.id, label: `${row.code} ${row.name}${row.vehicle_label ? ` · ${row.vehicle_label}` : ''}${row.period_key ? ` · ${row.period_key}` : ''}` }))} />}
        <div><Typography.Paragraph>有效期（最长一年）</Typography.Paragraph><DatePicker aria-label="分享有效期" showTime format="YYYY-MM-DD HH:mm" value={expiry} disabled={busy || loading} onChange={value => { setExpiry(value); onDirtyChange(true) }} disabledDate={value => value.isBefore(dayjs(), 'day') || value.isAfter(dayjs().add(365, 'day'), 'day')} /></div>
        <Button type="primary" loading={busy} disabled={loading || !!error || !expiry || !scopes.length || scopes.includes('selected_documents') && !selected.length} onClick={() => void create()}>生成分享链接</Button>
      </Space>
    </Card>
    {link && <Alert type="success" showIcon closable onClose={() => setLink('')} message="链接仅在此次创建后显示，请妥善转交" description={<Space direction="vertical" style={{ width: '100%' }}><Input.TextArea aria-label="新分享链接" readOnly value={link} autoSize /><Typography.Text>持有链接即可读取所选内容；需要收回时撤销链接。刷新网页后无法找回原令牌。</Typography.Text><Button onClick={async () => { try { await navigator.clipboard.writeText(link) } catch { setError('复制失败，请选中链接手动复制') } }}>复制分享链接</Button></Space>} />}
    <Card title="已创建分享" size="small" extra={<Button loading={loading} disabled={busy} onClick={() => void load()}>刷新列表</Button>}>
      <Table<ExternalShare> rowKey="id" size="small" dataSource={rows} loading={loading} pagination={{ pageSize: 10 }} scroll={{ x: 650 }} locale={{ emptyText: <Empty description="尚未创建外部分享" /> }} columns={[
        { title: '范围', render: (_, row) => <Space wrap>{row.scopes.map(scope => <Tag key={scope}>{SHARE_SCOPES.find(item => item.value === scope)?.label || scope}</Tag>)}{row.document_ids.length > 0 && <span>指定 {row.document_ids.length} 项</span>}</Space> },
        { title: '有效期', render: (_, row) => new Date(row.expires_at).toLocaleString() },
        { title: '状态', render: (_, row) => row.revoked_at ? <Tag>已撤销</Tag> : row.expired || Date.parse(row.expires_at) <= Date.now() ? <Tag>已到期</Tag> : <Tag color="green">有效</Tag> },
        { title: '操作', render: (_, row) => <Space><Button size="small" onClick={() => void showLogs(row.id)}>访问记录</Button>{!row.revoked_at && <Popconfirm okText="确认撤销" cancelText="保留分享" title="撤销后原链接立即失效，无法恢复。" onConfirm={() => revoke(row)}><Button danger size="small" disabled={busy}>撤销分享</Button></Popconfirm>}</Space> },
      ]} />
    </Card>
    <Drawer title="外部访问记录（最近50条）" open={!!logId} onClose={() => { logSequence.current++; setLogId(null) }} width={660}>
      {logError && <Alert type="error" message={logError} />}
      <Typography.Paragraph type="secondary">时间、直接连接IP、读取内容与结果；不记录令牌。</Typography.Paragraph>
      <Table<ExternalAccess> rowKey="id" loading={logLoading} dataSource={logs} size="small" scroll={{ x: 550 }} columns={[
        { title: '时间', render: (_, row) => new Date(row.time).toLocaleString() }, { title: 'IP', dataIndex: 'ip' },
        { title: '内容', render: (_, row) => `${({ bootstrap: '打开分享', view: '刷新看板', download: '资料下载', authorize: '验证' } as Record<string, string>)[row.action] || row.action}${row.resource_id ? ` · ${row.resource_id}` : ''}` },
        { title: '结果', dataIndex: 'status_code' },
      ]} />
    </Drawer>
  </Space>
}
