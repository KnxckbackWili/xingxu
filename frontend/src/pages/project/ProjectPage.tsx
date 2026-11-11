import { useMemo } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { Button, Dropdown, Modal, Result, Segmented, Skeleton, Switch, message } from 'antd'
import { DownloadOutlined, HistoryOutlined, LeftOutlined, MoreOutlined } from '@ant-design/icons'
import { api, errMsg } from '../../api/client'
import type { Project, Snapshot } from '../../api/types'
import { TextCell } from '../../components/Grid'
import { useAuth } from '../../stores/auth'
import { useLive } from '../../sync/useLive'
import { download } from '../../utils/format'
import { gapCounts, type TabProps } from './context'
import DocumentsTab from './DocumentsTab'
import IssuesTab from './IssuesTab'
import ItemsTab from './ItemsTab'
import VehiclesTab from './VehiclesTab'
import WorkTab from './WorkTab'
import './project.css'

const TABS = [
  { key: 'vehicles', label: '车辆', unit: '台没做完', view: VehiclesTab },
  { key: 'work', label: '工作', unit: '项没做', view: WorkTab },
  { key: 'issues', label: '问题', unit: '个没关', view: IssuesTab },
  { key: 'documents', label: '资料', unit: '份没交', view: DocumentsTab },
  { key: 'items', label: '物品', unit: '样没到', view: ItemsTab },
] as const
type TabKey = typeof TABS[number]['key']

export default function ProjectPage() {
  const { id = '', tab = 'vehicles' } = useParams()
  const [search, setSearch] = useSearchParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const base = `/projects/${id}`
  const live = useLive<Snapshot>(base)
  const snap = live.data
  const gaps = useMemo(() => (snap ? gapCounts(snap) : null), [snap])
  const todo = search.get('todo') === '1'
  const current = TABS.find((item) => item.key === tab) ?? TABS[0]

  if (!snap) {
    return live.error
      ? <Result status="warning" title="打不开这个项目" subTitle={live.error} extra={<Button type="primary" onClick={() => navigate('/')}>回到首页</Button>} />
      : <Skeleton active paragraph={{ rows: 8 }} />
  }
  const project = snap.project
  const setField = async (field: keyof Project & string, to: unknown) => {
    const from = project[field]
    live.mutate((data) => ({ ...data, project: { ...data.project, [field]: to } }))
    try {
      await live.track(api.patch(base, { [field]: typeof to === 'boolean' ? { to } : { from, to } }))
    } catch (failure) {
      live.mutate((data) => ({ ...data, project: { ...data.project, [field]: from } }))
      message.error(errMsg(failure))
    }
  }
  const remove = () => Modal.confirm({
    title: `删除项目“${project.name}”？`, content: '删除后 30 天内可以在“设置 → 已删除的项目”里恢复。', okText: '删除', okButtonProps: { danger: true }, cancelText: '取消',
    onOk: async () => { try { await api.delete(base); message.success('项目已删除'); navigate('/') } catch (failure) { message.error(errMsg(failure)) } },
  })
  const props: TabProps = { snap, live, base, me: { id: user?.id ?? '', name: user?.display_name ?? '' }, todo }
  const View = current.view
  const go = (key: TabKey) => navigate(`/projects/${id}/${key}${todo ? '?todo=1' : ''}`)

  return <div className="project-page">
    <header className="project-head">
      <Link to="/" className="project-back"><LeftOutlined /> 全部项目</Link>
      <div className="project-title-row">
        <h1 className="project-title"><TextCell value={project.name} label="项目名称" required strong onCommit={(next) => setField('name', next)} /></h1>
        <div className="project-actions">
          <Segmented aria-label="项目状态" value={project.is_closed ? 'closed' : 'open'} options={[{ value: 'open', label: '进行中' }, { value: 'closed', label: '已结束' }]}
            onChange={(value) => void setField('is_closed', value === 'closed')} />
          <Button icon={<HistoryOutlined />} onClick={() => navigate(`/history?project=${id}`)}>操作记录</Button>
          <Button icon={<DownloadOutlined />} onClick={() => download(`${base}/export.xlsx`)}>导出 Excel</Button>
          {user?.role === 'admin' && <Dropdown trigger={['click']} menu={{ items: [{ key: 'delete', label: '删除项目', danger: true, onClick: remove }] }}>
            <Button icon={<MoreOutlined />} aria-label="更多" />
          </Dropdown>}
        </div>
      </div>
      <div className="project-meta">
        <label><span>合同号</span><TextCell value={project.contract_no} label="合同号" placeholder="未填" onCommit={(next) => setField('contract_no', next)} /></label>
        <label><span>客户</span><TextCell value={project.customer} label="客户" placeholder="未填" onCommit={(next) => setField('customer', next)} /></label>
        <label className="is-wide"><span>备注</span><TextCell value={project.note} label="项目备注" placeholder="未填" onCommit={(next) => setField('note', next)} /></label>
      </div>
      <nav className="project-tabs" aria-label="项目内容">
        {TABS.map((item) => {
          const count = gaps?.[item.key] ?? 0
          return <button key={item.key} type="button" className={item.key === current.key ? 'is-active' : ''} aria-current={item.key === current.key ? 'page' : undefined}
            aria-label={`${item.label}${count ? `，${count} ${item.unit}` : '，齐了'}`} onClick={() => go(item.key)}>
            {item.label}{count > 0 ? <b className="tab-count">{count}</b> : <i className="tab-ok" aria-hidden="true">✓</i>}
          </button>
        })}
        <label className="project-todo"><Switch size="small" checked={todo} aria-label="只看没做的"
          onChange={(checked) => setSearch(checked ? { todo: '1' } : {}, { replace: true })} />只看没做的</label>
      </nav>
    </header>
    {live.error && <p className="project-offline" role="status">{live.error}。恢复后会自动同步。</p>}
    <View {...props} />
  </div>
}
