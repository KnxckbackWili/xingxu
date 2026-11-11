import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Dropdown, Modal, Skeleton, Switch, message } from 'antd'
import { CopyOutlined, DeleteOutlined, DownloadOutlined, MoreOutlined, PlusOutlined } from '@ant-design/icons'
import { api, errMsg, newId } from '../api/client'
import type { Template, VehicleType } from '../api/types'
import { AddLine, TextCell } from '../components/Grid'
import { promptText } from '../components/prompt'
import { useLive } from '../sync/useLive'
import { download } from '../utils/format'
import './Templates.css'

function Types() {
  const live = useLive<VehicleType[]>('/vehicle-types')
  const save = async (row: VehicleType, body: Partial<VehicleType>) => {
    live.mutate((rows) => rows.map((item) => (item.id === row.id ? { ...item, ...body } : item)))
    try { await live.track(api.patch(`/vehicle-types/${row.id}`, body)) } catch (failure) { live.refresh(); message.error(errMsg(failure)) }
  }
  const remove = (row: VehicleType) => Modal.confirm({
    title: `删除车型“${row.name}”？`, content: '已经录入的车辆不受影响，只是以后不能再从下拉里选它。', okText: '删除', okButtonProps: { danger: true }, cancelText: '取消',
    onOk: () => live.track(api.delete(`/vehicle-types/${row.id}`)).catch((failure) => message.error(errMsg(failure))),
  })
  return <section className="types" aria-label="车型库">
    <header className="section-head"><h2>车型库</h2><p>录车时“型号”一栏从这里选。停用的型号不再出现在下拉里。</p></header>
    <div className="grid-wrap">
      {!live.data && <Skeleton active paragraph={{ rows: 3 }} style={{ padding: 16 }} />}
      <ul className="type-list">{(live.data ?? []).map((row) => <li key={row.id} className={row.is_enabled ? '' : 'is-off'}>
        <TextCell value={row.name} label="型号" required strong onCommit={(next) => save(row, { name: next })} />
        <TextCell value={row.note} label="备注" placeholder="备注" onCommit={(next) => save(row, { note: next })} />
        <label className="type-on"><Switch size="small" checked={row.is_enabled} aria-label={`${row.name} 启用`} onChange={(checked) => void save(row, { is_enabled: checked })} />{row.is_enabled ? '在用' : '停用'}</label>
        <button type="button" className="grid-icon" aria-label={`删除车型 ${row.name}`} onClick={() => remove(row)}><DeleteOutlined /></button>
      </li>)}</ul>
      <AddLine placeholder="输入型号后回车，新增一个车型" onAdd={async (text) => { try { await live.track(api.post('/vehicle-types', { name: text })) } catch (failure) { message.error(errMsg(failure)); throw failure } }} />
    </div>
  </section>
}

export default function Templates() {
  const live = useLive<Template[]>('/templates')
  const navigate = useNavigate()
  const [busy, setBusy] = useState(false)
  const create = async () => {
    const name = await promptText('新建模板', '', '模板名称，例如：潜伏式项目')
    if (!name) return
    setBusy(true)
    try { const { data } = await api.post('/templates', { id: newId(), name }); navigate(`/templates/${data.id}`) } catch (failure) { message.error(errMsg(failure)) } finally { setBusy(false) }
  }
  const copy = async (template: Template) => {
    try { const { data } = await api.post(`/templates/${template.id}/copy`, {}); message.success('已复制'); navigate(`/templates/${data.id}`) } catch (failure) { message.error(errMsg(failure)) }
  }
  const remove = async (template: Template) => {
    try {
      await live.track(api.delete(`/templates/${template.id}`))
      const key = `template-${template.id}`
      message.open({ key, type: 'success', duration: 6, content: <span>已删除　<a onClick={() => { message.destroy(key); void live.track(api.post(`/templates/${template.id}/restore`)) }}>撤销</a></span> })
    } catch (failure) { message.error(errMsg(failure)) }
  }
  return <div className="templates">
    <header className="page-head">
      <div><h1>模板和车型库</h1><p>模板是四张清单：工作、资料、车辆环节、物品。新建项目时选一个，清单就带进项目。</p></div>
      <Button type="primary" icon={<PlusOutlined />} loading={busy} onClick={() => void create()}>新建模板</Button>
    </header>
    {!live.data && <Skeleton active />}
    <div className="template-cards">{(live.data ?? []).map((template) => <article key={template.id} className="template-card">
      <button type="button" className="template-open" onClick={() => navigate(`/templates/${template.id}`)}>
        <b>{template.name}</b>
        <span>工作 {template.counts?.work ?? 0} · 资料 {template.counts?.document ?? 0} · 环节 {template.counts?.step ?? 0} · 物品 {template.counts?.item ?? 0}</span>
        {template.note && <small>{template.note}</small>}
      </button>
      <Dropdown trigger={['click']} placement="bottomRight" menu={{ items: [
        { key: 'copy', icon: <CopyOutlined />, label: '复制一份', onClick: () => void copy(template) },
        { key: 'export', icon: <DownloadOutlined />, label: '导出 Excel', onClick: () => download(`/templates/${template.id}/export.xlsx`) },
        { key: 'delete', icon: <DeleteOutlined />, label: '删除', danger: true, onClick: () => void remove(template) },
      ] }}><button type="button" className="grid-icon" aria-label={`${template.name} 的更多操作`}><MoreOutlined /></button></Dropdown>
    </article>)}</div>
    {live.data?.length === 0 && <p className="tab-empty">还没有模板。</p>}
    <Types />
  </div>
}
