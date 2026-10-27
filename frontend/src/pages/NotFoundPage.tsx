import { Button, Result } from 'antd'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../stores/auth'
import { systemHomeRoute } from '../constants/nav'

export default function NotFoundPage() {
  const navigate = useNavigate()
  const { user } = useAuth()
  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <Result
        status="404"
        title="404"
        subTitle="页面不存在或已被移动"
        extra={
          <Button type="primary" onClick={() => navigate(user ? systemHomeRoute(user) : '/login')}>
            返回首页
          </Button>
        }
      />
    </div>
  )
}
