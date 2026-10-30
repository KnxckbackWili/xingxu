import { useEffect, useState } from 'react'
import { Card, Typography, Spin, Empty, Avatar, Space, Tag, Button, Alert, Input, Switch } from 'antd'
import { UserOutlined } from '@ant-design/icons'
import { api } from '../../../api/client'
import { formatDateTime } from '../../../utils/date'
import { formatAuditDetail } from '../../../utils/auditDetail'
import { WorkPageHeader } from '../../../components/WorkPage'

interface LogT {
  id: string
  operator_name: string
  detail: string
  created_at: string
}

/** 变更记录：按操作人分组 */
export default function HistoryPage({ projectId }: { projectId: string }) {
  const [groups, setGroups] = useState<{ name: string; logs: LogT[] }[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const [retry, setRetry] = useState(0)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [search, setSearch] = useState('')
  const [includeAccess, setIncludeAccess] = useState(false)

  useEffect(() => {
    let active = true
    setLoading(true); setLoadError(false); setGroups([])
    setExpanded(new Set())
    const load = async () => {
      try {
        const r = await api.get(`/projects/${projectId}/logs`, includeAccess ? { params: { include_access: true } } : undefined)
        if (!active) return
        const map = new Map<string, LogT[]>()
        r.data.forEach((l: LogT) => {
          const key = l.operator_name || '系统'
          if (!map.has(key)) map.set(key, [])
          map.get(key)!.push(l)
        })
        setGroups([...map.entries()].map(([name, logs]) => ({ name, logs })))
      } catch {
        if (active) setLoadError(true)
      } finally { if (active) setLoading(false) }
    }
    load()
    return () => { active = false }
  }, [projectId, retry, includeAccess])

  const term = search.trim().toLocaleLowerCase()
  const shown = groups.map(group => ({ ...group, logs: group.logs.filter(log => !term || `${group.name} ${formatAuditDetail(log.detail)} ${log.created_at ? formatDateTime(log.created_at) : ''}`.toLocaleLowerCase().includes(term)) })).filter(group => group.logs.length)

  return (
    <div className="project-history-page">
      <WorkPageHeader title="操作记录" description="查找谁在何时调整了项目、任务或日程。记录按操作人分组。" meta={loading ? '正在加载' : `${groups.reduce((count, group) => count + group.logs.length, 0)} 条已加载记录`} />
      <Space wrap size={16} style={{ marginBottom: 20 }}>
        <Input.Search aria-label="搜索已加载记录" placeholder="搜索操作人、日期或记录内容" value={search} allowClear onChange={event => setSearch(event.target.value)} style={{ maxWidth: 480 }} />
        <label className="project-history-access"><Switch size="small" checked={includeAccess} onChange={setIncludeAccess} aria-label="包含保密资料查看与下载记录" /> 包含保密资料查看与下载记录</label>
      </Space>
      {loading ? <div style={{ textAlign: 'center', padding: 60 }}><Spin /></div> : loadError ? <Alert type="error" showIcon message="变更记录加载失败" action={<Button onClick={() => setRetry(value => value + 1)}>重试</Button>} /> : !shown.length ? <Empty description={term ? '没有匹配的已加载记录' : '暂无变更记录'} style={{ padding: 40 }} /> : shown.map((g) => (
        <Card key={g.name} size="small" style={{ marginBottom: 12 }}
          title={
            <Space size={8}>
              <Avatar size={24} icon={<UserOutlined />} style={{ background: '#1677ff' }} />
              <Typography.Text strong>{g.name}</Typography.Text>
              <Tag>{g.logs.length} 条操作</Tag>
            </Space>
          }>
          <Space direction="vertical" size={4} style={{ width: '100%' }}>
            {(expanded.has(g.name) ? g.logs : g.logs.slice(0, 10)).map((l) => (
              <div key={l.id} className="project-history-row">
                <span>{formatAuditDetail(l.detail)}</span>
                <Typography.Text type="secondary" style={{ fontSize: 11, flexShrink: 0, marginLeft: 12 }}>
                  {l.created_at ? formatDateTime(l.created_at) : ''}
                </Typography.Text>
              </div>
            ))}
            {g.logs.length > 10 && <Button size="small" type="link" onClick={() => setExpanded(previous => { const next = new Set(previous); if (next.has(g.name)) next.delete(g.name); else next.add(g.name); return next })}>{expanded.has(g.name) ? '收起记录' : `展开其余 ${g.logs.length - 10} 条记录`}</Button>}
          </Space>
        </Card>
      ))}
    </div>
  )
}
