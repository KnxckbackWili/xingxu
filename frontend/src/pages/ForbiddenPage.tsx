import { Button, Result } from 'antd'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../stores/auth'
import { systemHomeRoute } from '../constants/nav'

/** 403：已登录但当前角色无权访问该区域（路由守卫渲染，不再静默重定向） */
export default function ForbiddenPage() {
  const navigate = useNavigate()
  const { user } = useAuth()
  return (
    <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 80 }}>
      <Result
        status="403"
        title="403"
        subTitle="当前账号无权访问这个页面（可能是角色不对，或该项目不属于你管理）"
        extra={
          <Button type="primary" onClick={() => navigate(user ? systemHomeRoute(user) : '/login')}>
            回到工作台
          </Button>
        }
      />
    </div>
  )
}
