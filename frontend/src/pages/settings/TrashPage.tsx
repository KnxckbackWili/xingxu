import { useCallback, useEffect, useState } from 'react'
import { Button, Modal, Skeleton, message } from 'antd'
import { api, errMsg } from '../../api/client'
import type { Project } from '../../api/types'
import { day } from '../../utils/format'

export default function TrashPage() {
  const [projects, setProjects] = useState<Project[] | null>(null)
  const load = useCallback(() => api.get('/trash/projects').then(({ data }) => setProjects(data)).catch((failure) => message.error(errMsg(failure))), [])
  useEffect(() => { void load() }, [load])
  const restore = async (project: Project) => {
    try { await api.post(`/projects/${project.id}/restore`); message.success('项目已恢复'); await load() } catch (failure) { message.error(errMsg(failure)) }
  }
  const purge = (project: Project) => Modal.confirm({
    title: `彻底清除“${project.name}”？`, content: '项目里的全部记录和文件会立即删除，不能再恢复。', okText: '彻底清除', okButtonProps: { danger: true }, cancelText: '取消',
    onOk: async () => { try { await api.delete(`/trash/projects/${project.id}`); await load() } catch (failure) { message.error(errMsg(failure)) } },
  })
  return <section aria-label="已删除的项目">
    <header className="section-head"><h2>已删除的项目</h2><p>删除的项目在这里保留 30 天，到期自动清除。</p></header>
    {!projects && <Skeleton active />}
    {projects?.length === 0 && <p className="tab-empty">没有已删除的项目。</p>}
    {projects && projects.length > 0 && <ul className="settings-list">{projects.map((project) => <li key={project.id}>
      <span className="settings-main"><b>{project.name}</b><small>{project.deleted_by_name || '有人'} 于 {day(project.deleted_at)} 删除</small></span>
      <span className="settings-actions"><Button size="small" type="primary" onClick={() => void restore(project)}>恢复</Button><Button size="small" danger onClick={() => purge(project)}>彻底清除</Button></span>
    </li>)}</ul>}
  </section>
}
