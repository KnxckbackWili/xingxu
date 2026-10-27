import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Input, QRCode, Space, Typography } from 'antd'
import { twoFactorApi, type AuthSession } from '../api/twoFactor'
import { useAuth } from '../stores/auth'
import { errMsg } from '../api/client'
import { useSubmitLock } from '../hooks/useSubmitLock'

export function RecoveryCodes({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  return <Space direction="vertical" style={{ width: '100%' }}>
    <Alert type="warning" showIcon message="请安全保存恢复码" description="每枚只能使用一次，完整恢复码只在本次显示。请保存到密码管理器或离线保管，勿发给他人。" />
    <Input.TextArea aria-label="一次性恢复码" readOnly rows={10} value={codes.join('\n')} autoComplete="off" />
    <Button type="primary" onClick={onDone}>我已安全保存</Button>
  </Space>
}

export default function MfaEnrollment({ challenge, onComplete, onCancel, onBusyChange }: { challenge: string; onComplete: (result: AuthSession) => void; onCancel: () => void; onBusyChange?: (busy: boolean) => void }) {
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string; expires_in: number } | null>(null)
  const [otp, setOtp] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [expired, setExpired] = useState(false)
  const lock = useSubmitLock()
  const generation = useRef(0)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    const current = ++generation.current
    let expiry: ReturnType<typeof setTimeout> | undefined
    setSetup(null); setError(''); setOtp(''); setExpired(false)
    void twoFactorApi.start(challenge).then(result => {
      if (generation.current !== current) return
      setSetup(result)
      expiry = setTimeout(() => { setSetup(null); setOtp(''); setExpired(true) }, result.expires_in * 1000)
    }).catch(reason => { if (generation.current === current) setError(errMsg(reason)) })
    return () => { generation.current++; if (expiry) clearTimeout(expiry) }
  }, [challenge, attempt])
  const confirm = async () => {
    if (!setup || expired || !lock.tryAcquire()) return
    const current = generation.current
    setLoading(true); onBusyChange?.(true); setError('')
    try {
      const result = await useAuth.getState().completeMfa(challenge, { otp }, true)
      if (generation.current === current) { setSetup(null); setOtp(''); onComplete(result); useAuth.getState().finishMfa() }
    } catch (reason) { if (generation.current === current) setError(errMsg(reason)) }
    finally { onBusyChange?.(false); lock.release(); if (generation.current === current) setLoading(false) }
  }
  return <Space direction="vertical" style={{ width: '100%' }}>
    <Alert type="info" showIcon message="设置二次验证" description="使用认证器扫描二维码，再填写当前六位验证码。二维码在本机生成，不发送给外部网站。" />
    {error && <Alert type="error" showIcon message={error} />}
    {expired && <Alert type="warning" showIcon message="登记步骤已过期，请返回重新登录或开始设置" />}
    {setup && <>
      <QRCode type="svg" value={setup.otpauth_uri} color="#000" bgColor="#fff" size={184} />
      <label htmlFor="mfa-manual-key">无法扫码时手动输入密钥</label><Input id="mfa-manual-key" readOnly value={setup.secret} autoComplete="off" />
      <Typography.Text type="secondary">验证码只能使用一次，请使用当前新生成的一组。</Typography.Text>
      <label htmlFor="mfa-enroll-otp">六位验证码</label><Input id="mfa-enroll-otp" value={otp} onChange={event => setOtp(event.target.value)} inputMode="numeric" autoComplete="one-time-code" maxLength={6} disabled={loading} onPressEnter={() => void confirm()} />
      <Button type="primary" disabled={!/^\d{6}$/.test(otp)} loading={loading} onClick={() => void confirm()}>确认启用</Button>
    </>}
    {!setup && !expired && <Button disabled={loading} onClick={() => setAttempt(value => value + 1)}>重新读取登记信息</Button>}
    <Button disabled={loading} onClick={onCancel}>取消登记</Button>
  </Space>
}
