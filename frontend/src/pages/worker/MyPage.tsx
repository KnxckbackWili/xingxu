import { Alert } from 'antd'
import { Link } from 'react-router-dom'
import { WorkPageHeader } from '../../components/WorkPage'
import { useAuth } from '../../stores/auth'
import { hasSystemPermission } from '../../constants/systemPermissions'
import RecordsPage from './RecordsPage'
import './worker.css'

/** 我的记录: one week, one list of what I actually recorded (the weekly report is the summary line above it). */
export default function MyPage() {
  const { user } = useAuth()
  return <div className="worker-work-page"><WorkPageHeader title="我的记录" description="按周看自己登记的完成、协助、修订和撤回。" primary={<Link to="/worker/week">返回本周</Link>} />
    {hasSystemPermission(user, 'personal.records.read') ? <RecordsPage /> : <Alert type="info" message="本人记录查看权限已关闭" />}</div>
}
