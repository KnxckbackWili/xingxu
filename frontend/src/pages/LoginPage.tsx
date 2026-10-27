import { useEffect, useRef, useState } from 'react'
import { useSubmitLock } from '../hooks/useSubmitLock'
import { useNavigate, useLocation } from 'react-router-dom'
import { Button, Checkbox, Form, Input, Typography, message, Alert, Space } from 'antd'
import { CheckCircleFilled, LockOutlined, SafetyCertificateOutlined, UserOutlined } from '@ant-design/icons'
import { useAuth } from '../stores/auth'
import { errMsg } from '../api/client'
import { systemHomeRoute } from '../constants/nav'
import { APP_VERSION } from '../version'
import { FONT } from '../constants/theme'
import BrandMark from '../components/BrandMark'
import MfaEnrollment, { RecoveryCodes } from '../components/MfaEnrollment'
import { twoFactorApi, type AuthSession } from '../api/twoFactor'
import type { User } from '../api'

const { Title, Text } = Typography

export default function LoginPage() {
  const { login, pendingMfa, completeMfa, cancelMfa } = useAuth()
  const [form] = Form.useForm()
  const [proof, setProof] = useState('')
  const [recover, setRecover] = useState(false)
  const [rebind, setRebind] = useState(false)
  const [codes, setCodes] = useState<string[] | null>(null)
  const [completedUser, setCompletedUser] = useState<User | null>(null)
  const submitLock = useSubmitLock()
  const active = useRef(true)
  useEffect(() => { active.current = true; return () => { active.current = false } }, [])
  const navigate = useNavigate()
  const location = useLocation()
  const [loading, setLoading] = useState(false)
  const [remember, setRemember] = useState(true)
  // 会话过期提示 + 登录后跳回原目标页（保留操作上下文）
  const params = new URLSearchParams(location.search)
  const expired = params.get('expired') === '1'
  const next = params.get('next') || ''
  const safeNext = next.startsWith('/') && !next.startsWith('//') && !next.startsWith('/login') && !/[\\\u0000-\u001f\u007f]/.test(next) ? next : ''

  const arrive = (user: User) => {
    message.success(`欢迎，${user.display_name}`)
    const landing = systemHomeRoute(user)
    navigate(safeNext || (landing === '/pm/dashboard' ? '/pm' : landing === '/worker/today' ? '/worker' : landing), { replace: true })
  }
  const completed = (result: AuthSession) => {
    setProof('')
    if (result.recovery_codes) { setCompletedUser(result.user); setCodes(result.recovery_codes) }
    else arrive(result.user)
  }
  const verify = async () => {
    if (!pendingMfa || !submitLock.tryAcquire()) return
    setLoading(true)
    try {
      if (rebind) {
        const challenge = await twoFactorApi.recoverLogin(pendingMfa.challenge, proof)
        if (active.current) { useAuth.getState().beginMfa(challenge); setProof('') }
        return
      }
      const result = await completeMfa(pendingMfa.challenge, recover ? { recovery_code: proof } : { otp: proof })
      if (active.current) completed(result)
    } catch (error) { if (active.current) message.error(errMsg(error)) }
    finally { submitLock.release(); if (active.current) setLoading(false) }
  }
  useEffect(() => () => {
    if (useAuth.getState().pendingMfa && !useAuth.getState().user) useAuth.getState().cancelMfa()
  }, [])
  useEffect(() => {
    if (!pendingMfa) return
    const timer = setTimeout(() => { cancelMfa(); setProof(''); message.warning('验证步骤已过期，请重新登录') }, pendingMfa.expires_in * 1000)
    return () => clearTimeout(timer)
  }, [pendingMfa, cancelMfa])
  const onFinish = async (values: { username: string; password: string }) => {
    if (!submitLock.tryAcquire()) return
    setLoading(true)
    try {
      const user = await login(values.username, values.password, remember)
      if (!active.current) return
      if ('challenge' in user) { form.resetFields(['password']); setProof(''); setRecover(false); setRebind(false); return }
      arrive(user)
    } catch (e) {
      if (active.current) message.error(errMsg(e))
    } finally {
      submitLock.release()
      if (active.current) setLoading(false)
    }
  }

  return (
    <main className="login-shell">
      <section className="login-context" aria-label="行序项目工作台">
        <div className="login-brand">
          <BrandMark subtitle prominent />
        </div>
        <div className="login-context-copy">
          <Text>从计划到交付</Text>
          <Title level={1}>让项目，<br />有序向前。</Title>
          <div className="login-process" aria-label="项目流程">
            {['项目规划', '现场执行', '交付验收'].map((item) => (
              <span key={item}><CheckCircleFilled />{item}</span>
            ))}
          </div>
        </div>
        <div className="login-context-footer">行序 · 项目工作台 · {APP_VERSION}</div>
      </section>

      <section className="login-form-section">
        <div className="login-form-wrap">
          <div className="login-mobile-brand"><BrandMark subtitle prominent /></div>
          <div className="login-form-heading">
            <SafetyCertificateOutlined />
            <div>
              <Title level={3}>登录工作台</Title>
              <Text type="secondary">使用你的工作账号登录</Text>
            </div>
          </div>
        {expired && (
          <Alert type="warning" showIcon message="登录已过期，请重新登录" />
        )}
        {codes ? <RecoveryCodes codes={codes} onDone={() => { setCodes(null); if (completedUser) arrive(completedUser) }} />
          : pendingMfa?.setup_required ? <MfaEnrollment key={pendingMfa.challenge} challenge={pendingMfa.challenge} onComplete={completed} onCancel={() => { cancelMfa(); setProof('') }} />
          : pendingMfa ? <Space direction="vertical" style={{ width: '100%' }}>
            <Alert type="info" showIcon message="完成二次验证" description={rebind ? "使用一枚恢复码开始重新绑定，验证新认证器后才能进入工作台。" : "密码已验证，完成这一步后才能进入工作台。"} />
            <label htmlFor="login-mfa-code">{recover ? '一次性恢复码' : '六位验证码'}</label>
            <Input.Password id="login-mfa-code" value={proof} onChange={event => setProof(event.target.value)} autoComplete="one-time-code" inputMode={recover ? 'text' : 'numeric'} maxLength={recover ? 64 : 6} disabled={loading} onPressEnter={() => void verify()} />
            <Button type="primary" loading={loading} disabled={!proof} onClick={() => void verify()}>{rebind ? '验证恢复码并重新绑定' : '验证并登录'}</Button>
            <Button type="link" disabled={loading} onClick={() => { setRecover(value => !value); setRebind(false); setProof('') }}>{recover ? '使用认证器验证码' : '使用恢复码'}</Button>
            <Button type="link" disabled={loading} onClick={() => { setRecover(true); setRebind(true); setProof('') }}>认证器丢失，使用恢复码重新绑定</Button>
            <Button disabled={loading} onClick={() => { cancelMfa(); setProof('') }}>返回账号密码登录</Button>
          </Space> : <Form form={form} name="login" onFinish={onFinish} size="large" layout="vertical" requiredMark={false}>
          <Form.Item name="username" label="账号" rules={[{ required: true, message: '请输入账号' }]}>
            <Input prefix={<UserOutlined />} placeholder="填写账号" autoComplete="username" />
          </Form.Item>
          <Form.Item
            name="password"
            label={
              <span className="login-password-label">
                <span>密码</span>
                <Typography.Link className="login-help-link" style={{ fontSize: FONT.small, fontWeight: 400 }} onClick={() => message.info('请联系系统管理员重置密码')}>
                  忘记密码？
                </Typography.Link>
              </span>
            }
            rules={[{ required: true, message: '请输入密码' }]}
          >
            <Input.Password prefix={<LockOutlined />} placeholder="密码" autoComplete="current-password" />
          </Form.Item>
          <Form.Item style={{ marginBottom: 16 }}>
            <Checkbox checked={remember} onChange={(e) => setRemember(e.target.checked)}>
              记住登录状态
            </Checkbox>
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" block loading={loading}>
              登录
            </Button>
          </Form.Item>
        </Form>}
        <Text type="secondary" className="login-help">
          登录遇到困难？请联系系统管理员
        </Text>
        </div>
      </section>
    </main>
  )
}
