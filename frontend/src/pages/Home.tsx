import { Fragment, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Form, Input, InputNumber, Modal, Result, Select, Skeleton, message } from 'antd'
import { DownOutlined, PlusOutlined, RightOutlined } from '@ant-design/icons'
import { api, errMsg, newId } from '../api/client'
import type { Gaps, OverviewProject, Template } from '../api/types'
import { useLive } from '../sync/useLive'
import './Home.css'

const COLUMNS = [
  { key: 'vehicles', label: '车辆', unit: '台', verb: '还差' },
  { key: 'work', label: '工作', unit: '项', verb: '没做' },
  { key: 'issues', label: '问题', unit: '个', verb: '没关' },
  { key: 'documents', label: '资料', unit: '份', verb: '缺' },
  { key: 'items', label: '物品', unit: '样', verb: '没到' },
] as const
type Key = typeof COLUMNS[number]['key']

function count(gaps: Gaps, key: Key): number {
  return key === 'vehicles' ? gaps.vehicles.missing.length : gaps[key].length
}

function gapText(key: Key, amount: number): string {
  switch (key) {
    case 'vehicles': return `还差 ${amount} 台`
    case 'work': return `${amount} 项没做`
    case 'issues': return `${amount} 个没关`
    case 'documents': return `缺 ${amount} 份`
    default: return `${amount} 样没到`
  }
}

function Detail({ project }: { project: OverviewProject }) {
  const gaps = project.gaps!
  const groups: { key: Key; title: string; lines: string[] }[] = [
    { key: 'vehicles', title: '车辆没做完的环节', lines: gaps.vehicles.missing.map((row) => `${row.name}${row.fleet_no ? `（${row.fleet_no} 号）` : ''}：${row.missing.join('、')}`) },
    { key: 'work', title: '没做的工作', lines: gaps.work.map((row) => (row.stage ? `${row.stage} · ${row.name}` : row.name)) },
    { key: 'issues', title: '没关的问题', lines: gaps.issues.map((row) => row.name) },
    { key: 'documents', title: '没交的资料', lines: gaps.documents.map((row) => row.name) },
    { key: 'items', title: '没到的物品', lines: gaps.items.map((row) => row.name) },
  ]
  const missing = groups.filter((group) => group.lines.length)
  if (!missing.length) return <p className="home-detail-ok">这个项目什么都不缺。</p>
  return <div className="home-detail">{missing.map((group) => <section key={group.key}>
    <h4>{group.title}<span>{group.lines.length}</span></h4>
    <ul>{group.lines.slice(0, 30).map((line, index) => <li key={index}>{line}</li>)}{group.lines.length > 30 && <li>……还有 {group.lines.length - 30} 条</li>}</ul>
  </section>)}</div>
}

function NewProject({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [form] = Form.useForm()
  const navigate = useNavigate()
  const [busy, setBusy] = useState(false)
  const templates = useLive<Template[]>(open ? '/templates' : null).data
  const submit = async () => {
    const values = await form.validateFields()
    setBusy(true)
    try {
      const { data } = await api.post('/projects', { id: newId(), ...values, vehicle_count: values.vehicle_count ?? 0 })
      form.resetFields()
      onClose()
      navigate(`/projects/${data.id}`)
    } catch (failure) {
      message.error(errMsg(failure))
    } finally {
      setBusy(false)
    }
  }
  return <Modal open={open} title="新建项目" okText="创建" cancelText="取消" confirmLoading={busy} onOk={() => void submit()} onCancel={onClose} destroyOnClose>
    <Form form={form} layout="vertical" initialValues={{ vehicle_count: 0 }} preserve={false}>
      <Form.Item name="name" label="项目名称" rules={[{ required: true, whitespace: true, message: '请填写项目名称' }]}><Input maxLength={200} autoFocus placeholder="例如：苏州某工厂 12 台" /></Form.Item>
      <Form.Item name="contract_no" label="合同号"><Input maxLength={100} /></Form.Item>
      <Form.Item name="customer" label="客户"><Input maxLength={200} /></Form.Item>
      <Form.Item name="template_id" label="模板" extra="工作、资料、车辆环节、物品四张清单会从模板带进项目，之后可以随便改。">
        <Select allowClear placeholder="不用模板，从空的开始" options={(templates ?? []).map((template) => ({ value: template.id, label: template.name }))} />
      </Form.Item>
      <Form.Item name="vehicle_count" label="车辆台数" extra="先占好位置，车辆编号之后再填；也可以填 0，稍后导入。"><InputNumber min={0} max={200} precision={0} style={{ width: 140 }} /></Form.Item>
    </Form>
  </Modal>
}

export default function Home() {
  const live = useLive<{ projects: OverviewProject[] }>('/overview')
  const navigate = useNavigate()
  const [open, setOpen] = useState<Set<string>>(new Set())
  const [creating, setCreating] = useState(false)
  const [showClosed, setShowClosed] = useState(false)
  if (!live.data) {
    return live.error ? <Result status="warning" title="读不到项目" subTitle={live.error} extra={<Button type="primary" onClick={live.refresh}>重试</Button>} /> : <Skeleton active paragraph={{ rows: 6 }} />
  }
  const active = live.data.projects.filter((project) => !project.is_closed)
  const closed = live.data.projects.filter((project) => project.is_closed)
  const toggle = (id: string) => setOpen((current) => { const next = new Set(current); if (next.has(id)) next.delete(id); else next.add(id); return next })
  const cell = (project: OverviewProject, key: Key) => {
    const gaps = project.gaps!
    const amount = count(gaps, key)
    const total = key === 'vehicles' ? gaps.vehicles.total : null
    if (key === 'vehicles' && total === 0) return <span className="gap-none">没有车辆</span>
    return <button type="button" className={`gap${amount ? ' is-missing' : ' is-ok'}`}
      onClick={() => navigate(`/projects/${project.id}/${key}${amount ? '?todo=1' : ''}`)}>
      {amount ? gapText(key, amount) : '齐了'}
      {total !== null && <small>{total - amount} / {total} 台做完</small>}
    </button>
  }
  return <div className="home">
    <header className="page-head">
      <div><h1>项目</h1><p>哪里缺什么、哪里还没做，都在这张表里。点数字直接过去。</p></div>
      <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>新建项目</Button>
    </header>
    {active.length === 0 && <div className="home-empty"><p>还没有进行中的项目。</p><Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>新建项目</Button></div>}
    {active.length > 0 && <div className="grid-wrap"><table className="home-table" aria-label="进行中的项目">
      <thead><tr><th>项目</th>{COLUMNS.map((column) => <th key={column.key}>{column.label}</th>)}</tr></thead>
      <tbody>{active.map((project) => <Fragment key={project.id}>
        <tr>
          <td className="home-name-cell" data-label="项目"><div className="home-name">
            <button type="button" className="home-expand" aria-expanded={open.has(project.id)} aria-label={`${open.has(project.id) ? '收起' : '展开'} ${project.name} 的缺口明细`} onClick={() => toggle(project.id)}>
              {open.has(project.id) ? <DownOutlined /> : <RightOutlined />}</button>
            <a onClick={() => navigate(`/projects/${project.id}`)}><b>{project.name}</b>{(project.customer || project.contract_no) && <small>{[project.customer, project.contract_no].filter(Boolean).join(' · ')}</small>}</a>
          </div></td>
          {COLUMNS.map((column) => <td key={column.key} data-label={column.label}>{cell(project, column.key)}</td>)}
        </tr>
        {open.has(project.id) && <tr className="home-more"><td colSpan={6}><Detail project={project} /></td></tr>}
      </Fragment>)}</tbody>
    </table></div>}
    {closed.length > 0 && <section className="home-closed">
      <button type="button" aria-expanded={showClosed} onClick={() => setShowClosed(!showClosed)}>{showClosed ? <DownOutlined /> : <RightOutlined />} 已结束的项目 {closed.length}</button>
      {showClosed && <ul>{closed.map((project) => <li key={project.id}><a onClick={() => navigate(`/projects/${project.id}`)}>{project.name}</a><small>{[project.customer, project.contract_no].filter(Boolean).join(' · ')}</small></li>)}</ul>}
    </section>}
    <NewProject open={creating} onClose={() => setCreating(false)} />
  </div>
}
