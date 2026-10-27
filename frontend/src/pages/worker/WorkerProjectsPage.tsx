import { useEffect, useState } from 'react'
import { Card, List, Progress, Tag, Typography, Spin, Empty, Button, Space, Alert, Input } from 'antd'
import { useNavigate } from 'react-router-dom'
import { projectApi, type Project } from '../../api'
import { projectStatusMeta } from '../../constants/status'
import { canAccessNav } from '../../constants/nav'
import { useAuth } from '../../stores/auth'
import { WorkPageHeader, WorkSection } from '../../components/WorkPage'
import './WorkerWorkPages.css'

/** 现场人员项目列表：极简卡片，只保留“我参与/可见的项目”。 */
export default function WorkerProjectsPage() {
  const { user } = useAuth()
  const [search,setSearch] = useState('')
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()
  const [loadError, setLoadError] = useState(false)
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    let active = true
    setLoading(true)
    setLoadError(false)
    ;(async () => {
      try {
        const list = await projectApi.list(user?.id)
        if (!active) return
        setProjects(list)
        setLoading(false)
      } catch {
        if (active) setLoadError(true)
      } finally {
        if (active) setLoading(false)
      }
    })()
    return () => { active = false }
  }, [retry, user?.id])

  if (loading) return <div style={{ textAlign: 'center', padding: 60 }}><Spin /></div>

  const visible=projects.filter(project=>`${project.name} ${project.client || ''} ${project.location || ''}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()))
  return (
    <div className="worker-work-page worker-projects-page">
      <WorkPageHeader title="我的项目" description="只读查看当前项目、真实车辆进度和空白模板；实际工作在本周登记。"
        primary={<Button type="primary" href="/worker/week">进入本周</Button>} tools={<>{canAccessNav('/pm/project-recycle-bin',user)&&<Button onClick={()=>navigate('/pm/project-recycle-bin')}>项目回收站</Button>}<Button onClick={()=>setRetry(value=>value+1)}>刷新</Button></>} />
      <WorkSection filters={<><Input.Search aria-label="搜索我的项目" placeholder="搜索项目、客户或地点" allowClear value={search} onChange={event=>setSearch(event.target.value)} /></>}>
      {loadError ? (
        <Alert type="warning" showIcon message="项目暂时无法加载" description="请检查网络后重试。加载失败不代表你没有参与项目。" action={<Button onClick={() => setRetry((value) => value + 1)}>重新加载</Button>} />
      ) : visible.length === 0 ? (
        <Empty description={search ? '没有匹配的项目，请调整搜索。' : '你还没有可见项目，请联系项目经理将你加入项目。'} style={{ padding: 40 }} />
      ) : (
        <List
          grid={{ gutter: 12, xs: 1, sm: 1, md: 2, lg: 2 }}
          dataSource={visible}
          renderItem={(p) => {
            const st = projectStatusMeta(p.status)
            const percent = p.vehicle_progress?.percent
            return (
              <List.Item>
                <Card className="worker-project-card" hoverable onClick={() => navigate(`/worker/projects/${p.id}`)}>
                  <Space direction="vertical" size={14} className="worker-project-card-content" style={{ width: '100%' }}>
                    <Space wrap className="worker-project-card-heading" style={{ width: '100%', justifyContent: 'space-between' }}>
                      <button className="worker-title-link" onClick={event=>{event.stopPropagation();navigate(`/worker/projects/${p.id}`)}}>{p.name}</button>

                      <Tag color={st.color}>{st.label}</Tag>
                    </Space>
                    <Typography.Text type="secondary" className="worker-project-location">
                      {p.client || '客户未填'} · {p.location || '地点未填'}
                    </Typography.Text>
                    {percent == null ? <Typography.Text type="secondary">进度暂不可用</Typography.Text> : <div className="worker-project-progress">
                      <Progress percent={percent} size="small" showInfo={false} style={{ flex: 1 }} aria-label="项目进度" />
                      <Typography.Text style={{ fontSize: 12 }}>{percent}%</Typography.Text>
                    </div>}
                    <Button className="worker-project-open" aria-label={`查看项目：${p.name}`} type="primary" ghost onClick={event=>{event.stopPropagation();navigate(`/worker/projects/${p.id}`)}}>查看项目</Button>

                  </Space>
                </Card>
              </List.Item>
            )
          }}
        />
      )}
      </WorkSection>
    </div>
  )
}
