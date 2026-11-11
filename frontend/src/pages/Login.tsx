import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Alert, Button, Form, Input, message } from 'antd'
import { LockOutlined, UserOutlined } from '@ant-design/icons'
import { errMsg, isAuthed } from '../api/client'
import BrandMark from '../components/BrandMark'
import { useAuth } from '../stores/auth'
import { APP_VERSION, SOURCE_URL } from '../version'
import './Login.css'

/** Where to go after signing in: only a path inside this app, never another site. */
export function safeNext(search: string): string {
  const next = new URLSearchParams(search).get('next') ?? ''
  return next.startsWith('/') && !next.startsWith('//') && !next.startsWith('/login') ? next : '/'
}

export default function Login() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [busy, setBusy] = useState(false)
  const expired = new URLSearchParams(location.search).get('expired') === '1'
  useEffect(() => { if (user && isAuthed()) navigate(safeNext(location.search), { replace: true }) }, [user, navigate, location.search])
  const submit = async (values: { username: string; password: string }) => {
    if (busy) return
    setBusy(true)
    try {
      await login(values.username.trim(), values.password)
      navigate(safeNext(location.search), { replace: true })
    } catch (failure) {
      message.error(errMsg(failure))
    } finally {
      setBusy(false)
    }
  }
  return <main className="login">
    <section className="login-card">
      <div className="login-brand"><BrandMark prominent /></div>
      <h1>登录</h1>
      <p className="login-sub">记下每个项目的车辆、工作、问题、资料和物品。</p>
      {expired && <Alert type="warning" showIcon message="登录已过期，请重新登录" style={{ marginBottom: 16 }} />}
      <Form layout="vertical" size="large" requiredMark={false} onFinish={submit}>
        <Form.Item name="username" label="用户名" rules={[{ required: true, message: '请输入用户名' }]}><Input prefix={<UserOutlined />} autoComplete="username" autoFocus /></Form.Item>
        <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}><Input.Password prefix={<LockOutlined />} autoComplete="current-password" /></Form.Item>
        <Button type="primary" htmlType="submit" block loading={busy}>登录</Button>
      </Form>
      <footer className="login-foot">行序 {APP_VERSION} · <a href={SOURCE_URL} target="_blank" rel="noreferrer">开源地址</a></footer>
    </section>
  </main>
}
