import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Card, Empty, Progress, Space, Spin, Table, Tag, Typography } from 'antd'
import { externalViewApi, type ExternalDocument, type ExternalView } from '../api/externalView'
import { STATUS_LABEL } from '../constants/status'

export default function ExternalViewPage() {
  const secret = useRef(new URLSearchParams(window.location.hash.slice(1)).get('token') || '')
  const session = useRef('')
  const sequence = useRef(0)
  const expiration = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const [view, setView] = useState<ExternalView | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [downloading, setDownloading] = useState<string | null>(null)
  const load = async (signal?: AbortSignal) => {
    const ticket = ++sequence.current
    clearTimeout(expiration.current); session.current = ''
    setBusy(true); setError(''); setView(null)
    try {
      if (!secret.current) throw new Error('链接不完整，请使用项目负责人提供的原始分享链接。')
      const result = await externalViewApi.bootstrap(secret.current, signal)
      if (ticket !== sequence.current) return
      session.current = result.session_token; setView(result.view)
      expiration.current = setTimeout(() => { session.current = ''; setView(null); setError('当前只读会话已到期，请刷新核对分享是否仍有效。') }, Math.max(0, Date.parse(result.session_expires_at) - Date.now()))
    } catch (failure) {
      if (ticket === sequence.current && !signal?.aborted) { session.current = ''; setError(failure instanceof Error ? failure.message : '无法读取分享，请重新打开原始链接。') }
    } finally { if (ticket === sequence.current) setBusy(false) }
  }
  useEffect(() => {
    // Strip the fragment immediately. Neither token is ever written to a URL,
    // log, cookie, browser storage, or the internal Axios/offline pipeline.
    window.history.replaceState(window.history.state, '', window.location.pathname)
    const controller = new AbortController()
    void load(controller.signal)
    return () => { controller.abort(); clearTimeout(expiration.current); sequence.current++; session.current = '' }
  }, [])
  const download = async (row: ExternalDocument) => {
    if (downloading || !session.current) return
    const ticket = sequence.current
    setDownloading(row.id); setError('')
    try {
      const blob = await externalViewApi.download(session.current, row)
      if (ticket !== sequence.current) return
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a'); link.href = url; link.download = row.file!.filename; link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (failure) {
      if (ticket === sequence.current) { setView(null); session.current = ''; setError(failure instanceof Error ? failure.message : '下载失败，请刷新分享后核对。') }
    } finally { if (ticket === sequence.current) setDownloading(null) }
  }
  return <main style={{ maxWidth: 1100, margin: '0 auto', padding: 24 }}>
    <Typography.Title level={2}>项目外部查看</Typography.Title>
    <Typography.Paragraph type="secondary">只读分享 · 仅显示负责人授权的内容 · 保密资料永不对外提供</Typography.Paragraph>
    <Space style={{ marginBottom: 16 }}><Button aria-label="刷新分享" loading={busy} disabled={!!downloading} onClick={() => void load()}>刷新分享</Button>{view && <Typography.Text>有效期至 {new Date(view.expires_at).toLocaleString()}</Typography.Text>}</Space>
    {error && <Alert type="warning" showIcon message="无法继续显示分享" description={error} />}
    {busy && <Spin aria-label="读取外部分享" />}
    {view && <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Typography.Title level={3}>{view.project_name}</Typography.Title>
      {view.project_progress && <Card title="项目进度" size="small">
        <Tag>{STATUS_LABEL[view.project_progress.status] || view.project_progress.status}</Tag>
        <Typography.Paragraph>{view.project_progress.start_date} — {view.project_progress.end_date}</Typography.Paragraph>
        {view.project_progress.percent == null ? <Typography.Text>数量待核对，进度暂未知</Typography.Text> : <Progress percent={view.project_progress.percent} />}
      </Card>}
      {view.vehicle_progress && <Card title="车辆进度表" size="small">
        {view.vehicle_progress.warnings.map((warning, index) => <Typography.Paragraph type="secondary" key={index}>{warning}</Typography.Paragraph>)}
        <Table rowKey={row => row.asset_code} size="small" pagination={{ pageSize: 15 }} dataSource={view.vehicle_progress.units} scroll={{ x: 650 }} locale={{ emptyText: <Empty description="尚无登记车辆" /> }} columns={[
          { title: '车号', dataIndex: 'asset_code', fixed: 'left' }, { title: '车型 / 型号', render: (_, row) => `${row.vehicle_type} ${row.model_name}` },
          ...view.vehicle_progress.steps.map(step => ({ title: step.name, key: step.key, render: (_: unknown, row: NonNullable<ExternalView['vehicle_progress']>['units'][number]) => row.cells[step.key]?.is_done ? <Tag color="green">已完成{row.cells[step.key].done_on ? ` · ${row.cells[step.key].done_on}` : ''}</Tag> : <Tag>待完成</Tag> })),
        ]} />
      </Card>}
      {view.documents && <Card title="已授权资料" size="small"><Table<ExternalDocument> rowKey="id" size="small" pagination={{ pageSize: 15 }} dataSource={view.documents} scroll={{ x: 600 }} locale={{ emptyText: <Empty description="当前范围没有可对外展示的资料" /> }} columns={[
        { title: '资料', render: (_, row) => <>{row.code} {row.name}{row.vehicle_label && ` · ${row.vehicle_label}`}{row.period_key && ` · ${row.period_key}`}</> },
        { title: '状态', render: (_, row) => row.status === 'submitted' ? '已提交' : row.status === 'waived' ? '不适用' : '待提交' },
        { title: '最新文件', render: (_, row) => row.file ? <Button type="link" disabled={!!downloading} loading={downloading === row.id} onClick={() => void download(row)}>{row.file.filename}</Button> : '暂无可下载文件' },
      ]} /></Card>}
    </Space>}
  </main>
}
