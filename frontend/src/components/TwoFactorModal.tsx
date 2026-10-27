import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Divider, Input, Modal, Space, Spin, Typography, message } from 'antd'
import { useNavigate } from 'react-router-dom'
import { twoFactorApi, type AuthSession, type MfaStatus } from '../api/twoFactor'
import { useAuth } from '../stores/auth'
import { errMsg } from '../api/client'
import { useSubmitLock } from '../hooks/useSubmitLock'
import MfaEnrollment, { RecoveryCodes } from './MfaEnrollment'

export default function TwoFactorModal({ open, onClose, afterClose }: { open: boolean; onClose: () => void; afterClose?: () => void }) {
  const { user, pendingMfa, beginMfa, cancelMfa, disableMfa } = useAuth()
  const [status, setStatus] = useState<MfaStatus | null>(null)
  const [password, setPassword] = useState('')
  const [otp, setOtp] = useState('')
  const [recovery, setRecovery] = useState('')
  const [codes, setCodes] = useState<string[] | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const generation = useRef(0)
  const lock = useSubmitLock()
  const navigate = useNavigate()
  const reset = () => { setPassword(''); setOtp(''); setRecovery(''); setCodes(null); setError('') }
  useEffect(() => {
    const current = ++generation.current
    reset(); setStatus(null)
    if (open && user) void twoFactorApi.status().then(result => { if (generation.current === current) setStatus(result) }).catch(reason => { if (generation.current === current) setError(errMsg(reason)) })
    return () => { generation.current++ }
  }, [open, user?.id])
  const close = () => {
    if (busy) return
    if (pendingMfa) cancelMfa()
    reset(); onClose()
  }
  const run = async (operation: () => Promise<void>) => {
    if (!lock.tryAcquire()) return
    const current = generation.current
    setBusy(true); setError('')
    try { await operation() }
    catch (reason) { if (generation.current === current) setError(errMsg(reason)) }
    finally { lock.release(); if (generation.current === current) setBusy(false) }
  }
  const begin = async (replace: boolean) => {
    const current = generation.current
    const challenge = replace ? await twoFactorApi.recover(password, recovery) : await twoFactorApi.setup(password)
    if (generation.current === current) { beginMfa(challenge); setPassword(''); setRecovery('') }
  }
  const completed = (result: AuthSession) => {
    setCodes(result.recovery_codes ?? null); setOtp(''); setPassword(''); setRecovery('')
    setStatus({ enabled: true, required: !!result.user.two_factor_required, can_enroll: true, recovery_codes_remaining: 10 })
  }
  return <Modal title="二次验证" open={open} footer={null} onCancel={close} afterClose={afterClose} destroyOnHidden maskClosable={!busy} keyboard={!busy} closable={!busy}>
    <Space direction="vertical" style={{ width: '100%' }}>
      {error && <Alert type="error" message={error} showIcon />}
      {codes ? <RecoveryCodes codes={codes} onDone={() => setCodes(null)} />
        : pendingMfa ? <MfaEnrollment key={pendingMfa.challenge} challenge={pendingMfa.challenge} onComplete={completed} onBusyChange={setBusy} onCancel={() => { cancelMfa(); reset() }} />
        : !status ? <Spin aria-label="读取二次验证状态" />
        : <>
          <Alert type={status.enabled ? 'success' : 'info'} showIcon message={status.enabled ? '已启用认证器验证' : '尚未启用二次验证'} description={status.required ? '公开部署要求管理员和项目经理启用二次验证，不能自行关闭。' : '启用后，登录还需认证器验证码或一枚恢复码。'} />
          {status.enabled ? <>
            <Typography.Text>剩余恢复码：{status.recovery_codes_remaining} 枚</Typography.Text>
            <Typography.Text type="secondary">验证码只能使用一次；刚登录时使用过的验证码，请等待下一组。</Typography.Text>
            <label htmlFor="settings-mfa-otp">当前六位验证码</label>
            <Input.Password id="settings-mfa-otp" value={otp} onChange={event => setOtp(event.target.value)} inputMode="numeric" autoComplete="one-time-code" maxLength={6} disabled={busy} />
            <Button disabled={busy || !/^\d{6}$/.test(otp)} loading={busy} onClick={() => void run(async () => {
              const current = generation.current
              const result = await twoFactorApi.codes(otp)
              if (generation.current === current) { setCodes(result.recovery_codes); setOtp(''); setStatus({ ...status, recovery_codes_remaining: result.recovery_codes.length }) }
            })}>重新生成恢复码</Button>
            <Button danger disabled={busy || status.required || !/^\d{6}$/.test(otp)} onClick={() => void run(async () => {
              const current = generation.current
              await disableMfa(otp)
              if (generation.current === current) { reset(); onClose(); navigate('/login', { replace: true }); message.success('二次验证已关闭，请重新登录') }
            })}>关闭二次验证并退出登录</Button>
            <Divider style={{ margin: '12px 0' }} />
            <Typography.Text strong>更换丢失的认证器</Typography.Text>
            <Typography.Text type="secondary">用当前密码和另一枚未使用的恢复码开始重新绑定；确认新认证器前，原验证持续生效。也可退出后在登录页用一枚恢复码直接重新绑定。</Typography.Text>
            <label htmlFor="settings-mfa-password">当前密码</label><Input.Password id="settings-mfa-password" value={password} onChange={event => setPassword(event.target.value)} autoComplete="current-password" disabled={busy} />
            <label htmlFor="settings-mfa-recovery">一次性恢复码</label><Input.Password id="settings-mfa-recovery" value={recovery} onChange={event => setRecovery(event.target.value)} autoComplete="off" maxLength={64} disabled={busy} />
            <Button disabled={busy || !password || !recovery} onClick={() => void run(() => begin(true))}>开始重新绑定</Button>
          </> : status.can_enroll ? <>
            <label htmlFor="settings-mfa-password">当前密码</label><Input.Password id="settings-mfa-password" value={password} onChange={event => setPassword(event.target.value)} autoComplete="current-password" disabled={busy} onPressEnter={() => { if (password) void run(() => begin(false)) }} />
            <Button type="primary" loading={busy} disabled={!password} onClick={() => void run(() => begin(false))}>开始设置认证器</Button>
          </> : <Typography.Text>当前角色无需登记二次验证。</Typography.Text>}
        </>}
    </Space>
  </Modal>
}
