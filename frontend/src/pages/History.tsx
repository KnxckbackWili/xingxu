import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Button, Select, Skeleton, message } from 'antd'
import { api, errMsg } from '../api/client'
import type { HistoryItem, Project } from '../api/types'
import Person from '../components/Person'
import { dayTime } from '../utils/format'
import './History.css'

const RESTORE: Record<string, (item: HistoryItem) => string> = {
  files: (item) => `/files/${item.row_id}/restore`,
  template: (item) => `/templates/${item.row_id}/restore`,
  rows: (item) => `/templates/${item.scope_id}/rows/${item.row_id}/restore`,
}

function sentence(item: HistoryItem): string {
  const target = `${item.kind_label}${item.row_label ? `“${item.row_label}”` : ''}`
  if (item.action === 'update' && item.field_label) return `把${target}的${item.field_label}从“${item.old_text || '空'}”改成“${item.new_text || '空'}”`
  if (item.action === 'update' && item.detail) return `${target}：${item.detail}`
  if (['create', 'delete', 'restore', 'purge'].includes(item.action)) return `${item.action_label}了${target}`
  return item.detail ? `${item.detail}${item.row_label ? `（${item.row_label}）` : ''}` : `${item.action_label}${target}`
}

export default function History() {
  const [search, setSearch] = useSearchParams()
  const project = search.get('project') ?? ''
  const person = search.get('user') ?? ''
  const [items, setItems] = useState<HistoryItem[] | null>(null)
  const [next, setNext] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [projects, setProjects] = useState<Project[]>([])
  const [people, setPeople] = useState<{ id: string; display_name: string }[]>([])
  const load = useCallback(async (before?: number) => {
    setBusy(true)
    try {
      const { data } = await api.get('/history', { params: { project_id: project || undefined, user_id: person || undefined, before } })
      setItems((current) => (before && current ? [...current, ...data.items] : data.items))
      setNext(data.next_before)
    } catch (failure) {
      message.error(errMsg(failure))
    } finally {
      setBusy(false)
    }
  }, [project, person])
  useEffect(() => { setItems(null); void load() }, [load])
  useEffect(() => {
    void api.get('/projects').then(({ data }) => setProjects(data)).catch(() => undefined)
    void api.get('/users/names').then(({ data }) => setPeople(data)).catch(() => undefined)
  }, [])
  const restore = async (item: HistoryItem) => {
    const path = RESTORE[item.kind]?.(item) ?? `/projects/${item.scope_id}/${item.kind}/${item.row_id}/restore`
    try { await api.post(path); message.success('已恢复'); void load() } catch (failure) { message.error(errMsg(failure)) }
  }
  const filter = (key: string, value: string | undefined) => {
    const params = new URLSearchParams(search)
    if (value) params.set(key, value); else params.delete(key)
    setSearch(params, { replace: true })
  }
  return <div className="history">
    <header className="page-head">
      <div><h1>操作记录</h1><p>谁在什么时候改了什么。被删除的记录 30 天内可以在这里恢复。</p></div>
      <div className="page-head-actions">
        <Select allowClear showSearch optionFilterProp="label" placeholder="全部项目" aria-label="按项目筛选" style={{ minWidth: 180 }} value={project || undefined}
          onChange={(value) => filter('project', value)} options={projects.map((item) => ({ value: item.id, label: item.name }))} />
        <Select allowClear showSearch optionFilterProp="label" placeholder="所有人" aria-label="按人筛选" style={{ minWidth: 130 }} value={person || undefined}
          onChange={(value) => filter('user', value)} options={people.map((item) => ({ value: item.id, label: item.display_name }))} />
      </div>
    </header>
    {!items && <Skeleton active paragraph={{ rows: 8 }} />}
    {items?.length === 0 && <p className="tab-empty">还没有记录。</p>}
    {items && items.length > 0 && <ol className="history-list" aria-label="操作记录">{items.map((item) => <li key={item.seq}>
      <span className="history-who"><Person name={item.user_name} /></span>
      <span className="history-what">{sentence(item)}
        {item.project_id && item.project_name && !project && <Link to={`/projects/${item.project_id}`} className="history-project">{item.project_name}</Link>}</span>
      <time className="history-when">{dayTime(item.created_at)}</time>
      {item.can_restore && <Button size="small" onClick={() => void restore(item)}>恢复</Button>}
    </li>)}</ol>}
    {next && <div className="history-more"><Button loading={busy} onClick={() => void load(next)}>看更早的</Button></div>}
  </div>
}
