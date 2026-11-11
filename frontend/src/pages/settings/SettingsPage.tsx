import { lazy, Suspense } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Segmented, Skeleton } from 'antd'
import TrashPage from './TrashPage'
import UsersPage from './UsersPage'
import './settings.css'

const BackupPage = lazy(() => import('./BackupPage'))
const UpdatesPage = lazy(() => import('./UpdatesPage'))
const TABS = [{ value: 'users', label: '账号' }, { value: 'backup', label: '备份' }, { value: 'updates', label: '软件更新' }, { value: 'trash', label: '已删除的项目' }]

export default function SettingsPage() {
  const { tab = 'users' } = useParams()
  const navigate = useNavigate()
  return <div className="settings">
    <header className="page-head"><div><h1>设置</h1><p>只有系统管理员能进这里。</p></div></header>
    <Segmented className="settings-tabs" aria-label="设置内容" options={TABS} value={TABS.some((item) => item.value === tab) ? tab : 'users'} onChange={(value) => navigate(`/settings/${value}`)} />
    <Suspense fallback={<Skeleton active />}>
      {tab === 'backup' ? <BackupPage /> : tab === 'updates' ? <UpdatesPage /> : tab === 'trash' ? <TrashPage /> : <UsersPage />}
    </Suspense>
  </div>
}
