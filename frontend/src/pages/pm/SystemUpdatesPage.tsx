import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Checkbox, Input, Modal, Result, Skeleton } from 'antd'
import { CheckOutlined, CloudDownloadOutlined, InfoCircleOutlined, LoadingOutlined, PlusOutlined, RightOutlined, ReloadOutlined, SettingOutlined } from '@ant-design/icons'
import { WorkPageHeader } from '../../components/WorkPage'
import { useAuth } from '../../stores/auth'
import { APP_VERSION } from '../../version'
import { errMsg } from '../../api/client'
import { getOfflineAccount } from '../../offline/queue'
import { systemUpdatesApi, type SystemUpdates, type UpdateCheck, type UpdateSource } from '../../api/systemUpdates'
import './SystemUpdatesPage.css'

type Draft = { name: string; repository_url: string; ref: string; allow_http: boolean; token: string; clear_token: boolean }
type Action = 'save' | 'check' | 'install' | 'add' | 'select' | 'delete'
type SourceIntent = { kind: 'add' | 'select' | 'delete'; revision: number; source?: UpdateSource }
const emptyDraft = (): Draft => ({ name: '', repository_url: '', ref: 'main', allow_http: false, token: '', clear_token: false })
const sourceDraft = (source: UpdateSource): Draft => ({ ...emptyDraft(), name: source.name || '我的 Gitea', repository_url: source.repository_url, ref: source.ref || 'main', allow_http: source.allow_http })
const jobBusy = (data: SystemUpdates | null) => !!data?.maintenance || (!!data?.job && !['succeeded', 'failed', 'rolled_back'].includes(data.job.status))
const validateDraft = (draft: Draft) => {
  if (!draft.name.trim()) return '请填写来源名称。'
  let url: URL
  try { url = new URL(draft.repository_url.trim()) } catch { return '请填写完整的 Gitea 仓库地址。' }
  if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password || url.search || url.hash || url.pathname.split('/').filter(Boolean).length < 2) return '请填写包含所属组织和仓库名的 HTTP 或 HTTPS 地址，不要在地址中填写令牌。'
  if (url.protocol === 'http:' && !draft.allow_http) return '使用局域网 HTTP 地址前，请勾选明确允许。'
  return ''
}
const draftInput = (draft: Draft, revision: number) => ({ name: draft.name.trim(), repository_url: draft.repository_url.trim(), ref: draft.ref.trim() || 'main', allow_http: draft.allow_http,
  revision, ...(draft.clear_token ? { clear_token: true } : draft.token ? { token: draft.token } : {}) })
const statusLabel: Record<string, string> = {
  queued: '等待更新', downloading: '下载更新', building: '准备新版本', backing_up: '自动备份', installing: '安装更新',
  verifying: '验证新版本', succeeded: '更新已完成', failed: '更新未完成', rolled_back: '已恢复更新前版本', needs_attention: '更新需要人工处理',
}
const checkTrusted = (check: UpdateCheck | null | undefined, data: SystemUpdates | null) => check?.trust?.status === 'trusted' && data?.runner.trust?.configured === true && data.runner.trust.protocol === 1
const trustedLabel = (check: UpdateCheck | null | undefined) => check?.trust?.method === 'signed_tag' ? '标签签名已验证' : check?.trust?.method === 'commit' ? '宿主已登记此仓库提交' : '宿主已验证此版本'
const unverifiedMessage = '宿主尚未验证此版本，请重新检查或联系部署管理员'
const updatePhases = ['downloading', 'building', 'backing_up', 'installing', 'verifying']
const phaseLabels = ['下载', '准备', '备份', '安装', '验证']
const dateLabel = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '尚无记录'

export default function SystemUpdatesPage() {
  const { user } = useAuth()
  if (!user?.id || user.role !== 'admin' || user.is_active === false) return <Result status="403" title="仅系统管理员可以管理软件更新" />
  // A different account gets a fresh editor; old callbacks cannot touch its
  // source, token, confirmation dialog or update status.
  return <UpdatesEditor key={user.id} actorId={user.id} />
}

function UpdatesEditor({ actorId }: { actorId: string }) {
  const [data, setData] = useState<SystemUpdates | null>(null)
  const dataRef = useRef<SystemUpdates | null>(null)
  const observedJob = useRef<string | null>(null)
  const [base, setBase] = useState<UpdateSource | null>(null)
  const [draft, setDraft] = useState<Draft>(emptyDraft)
  const [newSource, setNewSource] = useState<{ draft: Draft; revision: number } | null>(null)
  const [newSourceError, setNewSourceError] = useState('')
  const [sourceIntent, setSourceIntent] = useState<SourceIntent | null>(null)
  const [sourceNotice, setSourceNotice] = useState('')
  const [loading, setLoading] = useState(true)
  const [readError, setReadError] = useState('')
  const [actionError, setActionError] = useState('')
  const [busy, setBusy] = useState<Action | null>(null)
  const action = useRef<Action | null>(null)
  const [confirmation, setConfirmation] = useState<UpdateCheck | null>(null)
  const [awaitingInstall, setAwaitingInstall] = useState(false)
  const pendingInstall = useRef<{ commit: string; previousJob: string | undefined } | null>(null)
  const alive = useRef(true)
  const sequence = useRef(0)
  const reading = useRef<number | null>(null)
  const dirty = !!base && (draft.name !== (base.name || '我的 Gitea') || draft.repository_url !== base.repository_url || draft.ref !== (base.ref || 'main') || draft.allow_http !== base.allow_http || !!draft.token || draft.clear_token)
  const dirtyRef = useRef(dirty)
  dirtyRef.current = dirty
  const activeJob = jobBusy(data)
  const locked = !!busy || activeJob || awaitingInstall
  const editorStale = !!base && !!data && (base.id !== data.source.id || base.revision !== data.source.revision)
  const editorLocked = locked || !!newSource || !!sourceIntent || !!confirmation
  const currentAccount = () => alive.current && getOfflineAccount() === actorId

  const apply = (next: SystemUpdates, resetDraft = false) => {
    if (next.job && (['queued', ...updatePhases].includes(next.job.status) || action.current === 'install')) observedJob.current = next.job.id
    dataRef.current = next; setData(next); setReadError('')
    if (resetDraft || !dirtyRef.current) {
      setBase(next.source); setDraft(sourceDraft(next.source)); dirtyRef.current = false
    }
    const pending = pendingInstall.current
    if (pending && next.job && next.job.id !== pending.previousJob && next.job.target_commit === pending.commit) {
      pendingInstall.current = null; setAwaitingInstall(false)
    }
  }
  const load = async () => {
    if (!alive.current || action.current || reading.current !== null) return
    const request = ++sequence.current
    reading.current = request
    try {
      const next = await systemUpdatesApi.get()
      if (currentAccount() && request === sequence.current) apply(next)
    } catch (error) {
      if (currentAccount() && request === sequence.current) setReadError(errMsg(error))
    } finally {
      if (reading.current === request) reading.current = null
      if (alive.current && request === sequence.current) setLoading(false)
    }
  }
  useEffect(() => {
    alive.current = true
    void load()
    const timer = window.setInterval(() => { void load() }, 6000)
    return () => { alive.current = false; sequence.current++; reading.current = null; window.clearInterval(timer) }
  }, [])

  const begin = (kind: Action) => {
    if (!alive.current || action.current || jobBusy(dataRef.current) || pendingInstall.current) return false
    if (getOfflineAccount() !== actorId) {
      setActionError('当前登录状态已变化，请重新验证登录后操作。')
      return false
    }
    action.current = kind; sequence.current++; setBusy(kind); setActionError('')
    return true
  }
  const finish = () => { action.current = null; if (alive.current) setBusy(null) }
  const change = (patch: Partial<Draft>) => { dirtyRef.current = true; setDraft(current => ({ ...current, ...patch })); setActionError('') }
  const openNewSource = () => {
    const current = dataRef.current
    if (!current || locked) return
    setSourceIntent(null); setNewSourceError('')
    setNewSource({ draft: emptyDraft(), revision: current.source.revision })
  }
  const mutateSource = async (intent: SourceIntent) => {
    if (intent.kind === 'add') {
      if (!dataRef.current || locked || intent.revision !== dataRef.current.source.revision) return
      apply(dataRef.current, true); openNewSource(); return
    }
    if (!intent.source || intent.revision !== dataRef.current?.source.revision || !begin(intent.kind)) return
    try {
      const next = intent.kind === 'select'
        ? await systemUpdatesApi.selectSource(intent.source.id, intent.revision)
        : await systemUpdatesApi.deleteSource(intent.source.id, intent.revision)
      if (!currentAccount()) return
      apply(next, true); setSourceIntent(null); setConfirmation(null)
      setSourceNotice(intent.kind === 'select' ? `已切换至「${next.source.name}」，请重新检查版本。` : `已删除「${intent.source.name}」。当前使用「${next.source.name}」，请重新检查版本。`)
    } catch (error) { if (currentAccount()) { setSourceIntent(null); setActionError(errMsg(error)) } }
    finally { finish() }
  }
  const requestSource = (kind: SourceIntent['kind'], source?: UpdateSource) => {
    const current = dataRef.current
    if (!current || editorLocked || (kind === 'select' && source?.id === current.source.id)) return
    const intent = { kind, source, revision: current.source.revision }
    setActionError('')
    if (kind === 'delete' || dirtyRef.current) setSourceIntent(intent)
    else if (kind === 'add') openNewSource()
    else void mutateSource(intent)
  }
  const addSource = async () => {
    if (!newSource) return
    const invalid = validateDraft(newSource.draft)
    if (invalid) { setNewSourceError(invalid); return }
    if (newSource.revision !== dataRef.current?.source.revision) { setNewSourceError('来源列表已变化，请先采用最新列表后再添加。'); return }
    if (!begin('add')) return
    try {
      const next = await systemUpdatesApi.addSource(draftInput(newSource.draft, newSource.revision))
      if (!currentAccount()) return
      apply(next, true); setNewSource(null); setNewSourceError(''); setConfirmation(null)
      setSourceNotice(`已添加并切换至「${next.source.name}」，请检查版本。`)
    } catch (error) { if (currentAccount()) setNewSourceError(errMsg(error)) }
    finally { finish() }
  }
  const check = async () => {
    if (!dataRef.current?.source.repository_url || dirtyRef.current || newSource || sourceIntent || !begin('check')) return
    try {
      const next = await systemUpdatesApi.check(dataRef.current.source.revision)
      if (currentAccount()) { apply(next); setSourceNotice('') }
    } catch (error) { if (currentAccount()) { setActionError(errMsg(error)); setReadError(errMsg(error)) } }
    finally { finish() }
  }
  const save = async () => {
    if (!base || editorStale || newSource || sourceIntent) return
    const invalid = validateDraft(draft)
    if (invalid) { setActionError(invalid); return }
    if (!begin('save')) return
    let sourceSaved = false
    try {
      const saved = await systemUpdatesApi.saveSource(draftInput(draft, base.revision))
      if (!currentAccount()) return
      apply(saved, true); sourceSaved = true; setSourceNotice('来源已保存，正在检查版本。')
      // The check always uses the acknowledged source revision, never a draft.
      action.current = 'check'; setBusy('check')
      const next = await systemUpdatesApi.check(saved.source.revision)
      if (currentAccount()) { apply(next); setSourceNotice('') }
    } catch (error) { if (currentAccount()) { setActionError(errMsg(error)); if (sourceSaved) setSourceNotice('来源已保存，版本检查未完成。可稍后重新检查。') } }
    finally { finish() }
  }
  const validCheck = data?.check && data.check.source_revision === data.source.revision ? data.check : null
  const usedCheck = !!validCheck && !!data?.job && data.job.target_commit === validCheck.commit && Date.parse(validCheck.checked_at) <= Date.parse(data.job.created_at)
  const canInstall = !!validCheck?.update_available && checkTrusted(validCheck, data) && !!data?.runner.online && !usedCheck && !dirty && !locked && !newSource && !sourceIntent && !readError
  const install = async () => {
    const current = dataRef.current
    if (!confirmation || !current?.runner.online || dirtyRef.current || readError || current.check?.id !== confirmation.id ||
      current.check.source_revision !== current.source.revision || !current.check.update_available || !checkTrusted(current.check, current) || usedCheck || !begin('install')) return
    pendingInstall.current = { commit: confirmation.commit, previousJob: current.job?.id }
    setAwaitingInstall(true)
    try {
      const next = await systemUpdatesApi.install(confirmation.id)
      if (!currentAccount()) return
      apply(next); setConfirmation(null)
      // A successful acknowledgement can also be an idempotent receipt for
      // an existing job. It is a confirmed result even when its ID is unchanged.
      if (next.job?.target_commit === confirmation.commit) { pendingInstall.current = null; setAwaitingInstall(false) }
    } catch (error: any) {
      if (!currentAccount()) return
      setConfirmation(null)
      if (error.response?.status >= 400 && error.response.status < 500) {
        pendingInstall.current = null; setAwaitingInstall(false); setActionError(errMsg(error)); setReadError(errMsg(error))
      }
      // A lost install response can coincide with the application's restart.
      // Continue polling without offering a second install or declaring failure.
      else setReadError('安装请求结果待确认')
    } finally { finish() }
  }

  const runningJob = !!data?.job && ['queued', ...updatePhases].includes(data.job.status)
  const needsAttention = data?.job?.status === 'needs_attention'
  const hasUpdate = !!validCheck?.update_available && !usedCheck
  const previousAttemptFailed = usedCheck && ['failed', 'rolled_back'].includes(data?.job?.status || '')
  const noUpdate = !!validCheck && !validCheck.update_available
  const latest = noUpdate && validCheck?.commit === data?.current.commit
  const checking = busy === 'check'
  const trustRelevant = !!validCheck && !usedCheck
  const trustBlocked = trustRelevant && !checkTrusted(validCheck, data)
  const trustPending = trustBlocked && validCheck?.trust?.status === 'pending'
  const trustReason = validCheck?.trust?.status === 'trusted' && !checkTrusted(validCheck, data) ? unverifiedMessage : validCheck?.trust?.message || unverifiedMessage
  const needsReload = data?.job?.status === 'succeeded' && (observedJob.current === data.job.id || APP_VERSION !== `v${data.current.version}`)
  const phaseIndex = updatePhases.indexOf(data?.job?.phase || data?.job?.status || '')
  const heroTitle = awaitingInstall ? '正在确认安装请求' : needsAttention ? '更新需要处理' : runningJob ? statusLabel[data!.job!.status]
    : data?.maintenance ? '系统维护中' : checking ? '正在检查更新…' : readError ? '暂时无法确认更新'
      : previousAttemptFailed ? statusLabel[data!.job!.status] : trustBlocked ? trustPending ? '等待宿主验证版本' : '版本尚未通过宿主验证' : hasUpdate ? '有新版本可用' : latest ? '你的行序已是最新版本' : noUpdate ? '暂无可用更新' : usedCheck ? '更新已完成' : '让行序保持最新'
  const heroDescription = awaitingInstall || runningJob ? '请保持页面打开，完成后可刷新使用新版本。'
    : needsAttention ? '请先完成恢复处理，再继续更新。' : data?.maintenance ? '维护完成后，即可继续检查和安装。'
      : checking ? '正在从所选来源获取版本信息。' : readError ? '当前保留上次读取的信息，请稍后重试。'
        : previousAttemptFailed ? '请重新检查版本，再尝试安装。' : trustBlocked ? trustReason : hasUpdate ? `行序 ${validCheck?.version || '新版本'} 已准备好，安装前会自动备份。`
          : latest ? '你正在使用所选来源的最新版本。' : noUpdate ? '所选来源没有比当前版本更新的版本。' : usedCheck ? (needsReload ? '新版本已安装，刷新页面后即可使用。' : '新版本已安装，可以继续使用。') : '检查新版本，获得最新的功能和改进。'

  return <div className="system-updates-page">
    <WorkPageHeader title="软件更新" description="检查并安装行序的新版本。" />
    {loading && !data ? <div className="updates-loading"><Skeleton active paragraph={{ rows: 5 }} /></div> : !data ? <Alert type="error" showIcon message="更新信息暂时无法读取" description={readError} action={<Button onClick={() => void load()}>重试</Button>} /> : <>
      <section className="updates-hero" aria-labelledby="updates-hero-title">
        <div className="updates-app-icon"><img src="/xingxu-icon-192.png" width="88" height="88" alt="" />
          {latest && checkTrusted(validCheck, data) && !readError && !activeJob && !checking && <span className="updates-icon-check"><CheckOutlined aria-hidden="true" /></span>}
        </div>
        <p className="updates-product">行序 <span>项目工作台</span></p>
        <p className="updates-current-version">当前版本 <strong>{data.current.version || '尚未提供'}</strong></p>
        <div className="updates-hero-status" role="status" aria-live="polite">
          <h2 id="updates-hero-title">{(checking || runningJob || awaitingInstall) && <LoadingOutlined aria-hidden="true" />} {heroTitle}</h2>
          <p>{heroDescription}</p>
        </div>
        <div className="updates-primary-actions">
          <Button type={hasUpdate ? 'default' : 'primary'} onClick={() => void check()} loading={checking} disabled={editorLocked || dirty || !data.source.repository_url}>检查更新</Button>
          {(hasUpdate || previousAttemptFailed || runningJob || awaitingInstall || needsAttention) && <Button type="primary" icon={<CloudDownloadOutlined aria-hidden="true" />} disabled={!canInstall} onClick={() => { if (canInstall && validCheck) setConfirmation(validCheck) }}>安装更新</Button>}
        </div>
        {dirty ? <p className="updates-check-time">先保存更新来源的修改，再检查或安装。</p> : <p className="updates-check-time">{validCheck ? `上次检查：${dateLabel(validCheck.checked_at)}` : data.check ? '更新来源已变化，请重新检查版本。' : '尚未检查更新'}</p>}
      </section>
      <div className="updates-notices">
        {trustRelevant && !activeJob && !awaitingInstall && <Alert type={trustBlocked ? trustPending ? 'info' : 'warning' : 'success'} showIcon
          message={trustBlocked ? trustPending ? '宿主正在验证此版本' : validCheck?.trust?.status === 'rejected' ? '此版本未通过信任验证' : unverifiedMessage : trustedLabel(validCheck)}
          description={trustBlocked ? trustReason : '安装信任由部署管理员在宿主管理，网页不能修改。'} />}
        {(readError || (!data.runner.online && activeJob)) && <Alert type="warning" showIcon message={needsAttention ? '恢复处理尚未完成' : activeJob || awaitingInstall ? '更新中，等待服务恢复' : '暂时无法刷新更新状态'}
          description={needsAttention ? '需要部署管理员检查备份和日志，完成恢复后再继续。' : activeJob || awaitingInstall ? '保留上次进度并每 6 秒重试连接。请勿重复安装，恢复后会继续显示结果。' : `${readError}。当前显示上次读取的信息。`} />}
        {!data.runner.online && !activeJob && !awaitingInstall && <Alert type="info" showIcon message="安装功能暂不可用" description="更新服务未连接。仍可保存来源和检查版本；请参照部署文档接入更新服务后再安装。" />}
        {data.maintenance && <Alert type="warning" showIcon message="系统维护中" description="来源编辑、切换和安装已暂停，维护完成后可继续操作。" />}
        {actionError && <Alert type="error" showIcon message={actionError} />}
        {sourceNotice && <Alert type="success" showIcon message={sourceNotice} />}
      </div>
      {(data.job || awaitingInstall) && <section className={`updates-activity${needsAttention || data.job?.status === 'failed' ? ' updates-activity-warning' : ''}`} aria-label="更新进度">
        {awaitingInstall ? <div role="status"><strong>安装请求结果待确认</strong><p>正在等待更新服务返回状态，请勿重复安装。</p></div> : data.job && <>
          <div className="updates-activity-heading">
            <span className={`updates-activity-symbol${data.job.status === 'succeeded' ? ' is-success' : ''}`} aria-hidden="true">{data.job.status === 'succeeded' ? <CheckOutlined /> : runningJob ? <LoadingOutlined /> : <InfoCircleOutlined />}</span>
            <div className="updates-activity-copy"><strong>{statusLabel[data.job.status] || '更新处理中'}</strong><span>行序 {data.job.target_version || '目标版本未标注'} · {dateLabel(data.job.updated_at)}</span></div>
            {needsReload && <Button onClick={() => window.location.reload()}>刷新页面使用新版本</Button>}
          </div>
          {runningJob && <ol className="updates-phase-list" aria-label="更新步骤">{updatePhases.map((phase, index) => <li key={phase} className={index < phaseIndex ? 'is-complete' : index === phaseIndex ? 'is-current' : ''} aria-current={index === phaseIndex ? 'step' : undefined}><span aria-hidden="true">{index < phaseIndex ? <CheckOutlined /> : index + 1}</span>{phaseLabels[index]}</li>)}</ol>}
          {data.job.status !== 'succeeded' && <p className="updates-job-message" role="status" aria-live="polite">{data.job.message || statusLabel[data.job.phase] || '正在等待更新服务返回进度。'}</p>}
          {usedCheck && !activeJob && data.job.status !== 'succeeded' && <p className="updates-job-hint">此检查已用于上次更新；如需再次安装，请先重新检查更新。</p>}
        </>}
      </section>}
      <div className="updates-settings-group">
        <details className="updates-source-settings">
          <summary aria-label="更新来源"><span className="updates-row-icon"><SettingOutlined aria-hidden="true" /></span><span className="updates-row-title">更新来源</span><span className="updates-row-value">{dirty ? '有未保存的修改' : data.source.name || '我的 Gitea'}</span>{data.source.is_default && <span className="updates-default-label">默认</span>}<RightOutlined className="updates-chevron" aria-hidden="true" /></summary>
          <div className="updates-source-content">
            <p className="updates-source-intro">日常检查和安装使用当前来源。保存修改后会重新检查版本。</p>
          <div className="updates-form">
            <label htmlFor="updates-name">来源名称</label>
            <Input id="updates-name" value={draft.name} disabled={editorLocked} maxLength={60} autoComplete="off" placeholder="例如：我的 Gitea" onChange={event => change({ name: event.target.value })} />
            <label htmlFor="updates-repository">Gitea 仓库完整地址</label>
            <Input id="updates-repository" value={draft.repository_url} disabled={editorLocked} autoComplete="off" placeholder="https://git.example.com/team/workflow" onChange={event => change({ repository_url: event.target.value })} />
            <label htmlFor="updates-ref">分支或标签</label>
            <Input id="updates-ref" value={draft.ref} disabled={editorLocked} placeholder="main" onChange={event => change({ ref: event.target.value })} />
            <label htmlFor="updates-token">私有访问令牌</label>
            <Input.Password id="updates-token" value={draft.token} disabled={editorLocked || draft.clear_token} autoComplete="new-password" placeholder={base?.has_token ? '留空保留已保存的令牌' : '公开仓库可留空'} onChange={event => change({ token: event.target.value })} />
            <small><span>{base?.has_token ? '已保存访问令牌' : '尚未保存访问令牌'}</span> · 保存后不再显示令牌内容</small>
            {base?.has_token && draft.repository_url.trim() !== base.repository_url && <small>更换仓库会清除旧令牌；私有仓库请重新填写。</small>}
            {base?.has_token && <Checkbox checked={draft.clear_token} disabled={editorLocked} onChange={event => change({ clear_token: event.target.checked, token: '' })}>清除已保存的令牌</Checkbox>}
            <Checkbox checked={draft.allow_http} disabled={editorLocked} onChange={event => change({ allow_http: event.target.checked })}>允许局域网 HTTP 地址</Checkbox>
            {draft.allow_http && <small>HTTP 连接不加密，仅用于你信任的局域网。</small>}
            {dirty && <p className="updates-draft-note">来源有未保存的修改，保存后才能检查或安装。</p>}
            {dirty && editorStale && <Alert type="warning" message="来源已被其他管理员修改" description={`你的填写仍属于「${base?.name || '原来源'}」，已保留且不会写入其他来源；请载入最新配置后重新修改。`} action={<Button onClick={() => apply(data, true)} disabled={editorLocked}>放弃修改并载入最新配置</Button>} />}
            <Button type="primary" disabled={editorLocked || editorStale || !draft.repository_url.trim() || !draft.name.trim()} loading={busy === 'save'} onClick={() => void save()}>保存并检查更新</Button>
          </div>
          <details className="updates-advanced-sources">
            <summary aria-label="高级来源管理"><span className="updates-row-title">高级</span><span className="updates-row-value">多来源管理</span><RightOutlined className="updates-chevron" aria-hidden="true" /></summary>
            <div className="updates-advanced-content">
            <div className="updates-source-intro"><p>管理备用仓库或切换更新来源。每次切换后都需要重新检查，并由宿主验证目标版本。</p><Button icon={<PlusOutlined aria-hidden="true" />} disabled={editorLocked} onClick={() => requestSource('add')}>添加来源</Button></div>
          <div className="updates-source-picker">
            <label htmlFor="updates-source">当前更新来源</label>
            <div className="updates-source-picker-row">
              <select id="updates-source" value={data.source.id} disabled={editorLocked} onChange={event => {
                const source = data.sources?.find(item => item.id === event.target.value)
                if (source) requestSource('select', source)
              }}>
                {(data.sources?.length ? data.sources : [data.source]).map(source => <option key={source.id} value={source.id}>{source.name || '我的 Gitea'}{source.is_default ? '（默认）' : ''}</option>)}
              </select>
              {!data.source.is_default && data.source.id && <Button danger disabled={editorLocked} onClick={() => requestSource('delete', data.source)}>删除来源</Button>}
            </div>
            <small>{data.source.is_default ? '默认来源会一直保留，新增来源不会覆盖它。' : '正在使用自定义来源。删除后会自动回到默认来源。'}</small>
          </div>
            </div>
          </details>
          </div>
        </details>
        <div className="updates-connection-row"><span className="updates-row-icon"><span className={`updates-connection-dot${data.runner.online ? ' is-online' : ''}`} /></span><span className="updates-row-title">更新服务</span><span className="updates-row-value">{data.runner.online ? '已连接' : '更新服务未连接'}</span><Button type="text" className="updates-refresh" icon={<ReloadOutlined aria-hidden="true" />} aria-label="刷新状态" title="刷新状态" onClick={() => void load()} disabled={!!busy} /></div>
        <details className="updates-version-details">
          <summary aria-label="版本详情"><span className="updates-row-icon"><InfoCircleOutlined aria-hidden="true" /></span><span className="updates-row-title">版本详情</span><span className="updates-row-value">构建与连接信息</span><RightOutlined className="updates-chevron" aria-hidden="true" /></summary>
          <dl><div><dt>当前版本</dt><dd>{data.current.version || '尚未提供'}</dd></div><div><dt>当前构建</dt><dd><code>{data.current.commit || '尚未记录提交'}</code></dd></div>
            {validCheck && <><div><dt>来源版本</dt><dd>{validCheck.version || '版本未标注'}</dd></div><div><dt>来源构建</dt><dd><code>{validCheck.commit}</code></dd></div></>}
            {data.job && <div><dt>上次更新构建</dt><dd><code>{data.job.target_commit}</code></dd></div>}<div><dt>最近连接</dt><dd>{dateLabel(data.runner.last_seen)}</dd></div></dl>
        </details>
      </div>
      <p className="updates-footnote">安装信任由部署管理员在宿主管理，网页不能修改。<br />更新前自动备份，完成后由你刷新页面。</p>
    </>}
    <Modal title="添加更新来源" open={!!newSource} className="updates-source-modal" onCancel={() => { if (busy !== 'add') { setNewSource(null); setNewSourceError('') } }}
      onOk={() => void addSource()} okText="添加并使用" cancelText="取消" confirmLoading={busy === 'add'}
      okButtonProps={{ disabled: locked || !newSource?.draft.name.trim() || !newSource.draft.repository_url.trim() || newSource.revision !== data?.source.revision }}
      cancelButtonProps={{ disabled: busy === 'add' }} closable={busy !== 'add'} maskClosable={false} keyboard={busy !== 'add'}>
      {newSource && <>
        <p className="updates-modal-intro">添加后立即使用这个来源。已有来源和令牌会独立保留。</p>
        {newSourceError && <Alert type="error" showIcon message={newSourceError} />}
        {newSource.revision !== data?.source.revision && <Alert type="warning" showIcon message="来源列表已被其他管理员修改" description="新来源的填写已保留。核对当前来源后，采用最新列表再添加。"
          action={<Button disabled={locked} onClick={() => { if (dataRef.current) { setNewSource({ ...newSource, revision: dataRef.current.source.revision }); setNewSourceError('') } }}>保留填写并采用最新列表</Button>} />}
        <div className="updates-form">
          <label htmlFor="updates-new-name">新来源名称</label>
          <Input id="updates-new-name" value={newSource.draft.name} disabled={locked} maxLength={60} autoComplete="off" placeholder="例如：团队 Gitea"
            onChange={event => { setNewSource({ ...newSource, draft: { ...newSource.draft, name: event.target.value } }); setNewSourceError('') }} />
          <label htmlFor="updates-new-repository">新来源仓库地址</label>
          <Input id="updates-new-repository" value={newSource.draft.repository_url} disabled={locked} autoComplete="off" placeholder="https://git.example.com/team/workflow"
            onChange={event => { setNewSource({ ...newSource, draft: { ...newSource.draft, repository_url: event.target.value } }); setNewSourceError('') }} />
          <label htmlFor="updates-new-ref">新来源分支或标签</label>
          <Input id="updates-new-ref" value={newSource.draft.ref} disabled={locked} placeholder="main"
            onChange={event => { setNewSource({ ...newSource, draft: { ...newSource.draft, ref: event.target.value } }); setNewSourceError('') }} />
          <label htmlFor="updates-new-token">新来源访问令牌</label>
          <Input.Password id="updates-new-token" value={newSource.draft.token} disabled={locked} autoComplete="new-password" placeholder="公开仓库可留空"
            onChange={event => { setNewSource({ ...newSource, draft: { ...newSource.draft, token: event.target.value } }); setNewSourceError('') }} />
          <small>仅用于这个来源，添加后不再显示令牌内容。</small>
          <Checkbox checked={newSource.draft.allow_http} disabled={locked}
            onChange={event => { setNewSource({ ...newSource, draft: { ...newSource.draft, allow_http: event.target.checked } }); setNewSourceError('') }}>允许新来源使用局域网 HTTP 地址</Checkbox>
          {newSource.draft.allow_http && <small>HTTP 连接不加密，仅用于你信任的局域网。</small>}
        </div>
      </>}
    </Modal>
    <Modal title={sourceIntent?.kind === 'delete' ? '删除更新来源' : '放弃未保存的修改？'} open={!!sourceIntent}
      onCancel={() => { if (!busy) setSourceIntent(null) }} onOk={() => { if (sourceIntent) void mutateSource(sourceIntent) }}
      okText={sourceIntent?.kind === 'delete' ? '删除并返回默认来源' : sourceIntent?.kind === 'add' ? '放弃修改并添加' : '放弃修改并切换'} cancelText="保留并返回"
      confirmLoading={busy === 'select' || busy === 'delete'} okButtonProps={{ danger: sourceIntent?.kind === 'delete', disabled: locked || sourceIntent?.revision !== data?.source.revision }}
      cancelButtonProps={{ disabled: !!busy }} closable={!busy} maskClosable={false} keyboard={!busy}>
      {sourceIntent?.revision !== data?.source.revision && <Alert type="warning" showIcon message="来源列表已变化，请返回后重新选择。" />}
      {sourceIntent?.kind === 'delete' ? <p>将删除「{sourceIntent.source?.name}」及其已保存的访问令牌，并自动使用默认来源。</p>
        : <p>{sourceIntent?.kind === 'add' ? '添加来源前' : `切换至「${sourceIntent?.source?.name}」前`}，需要放弃当前来源尚未保存的修改。</p>}
      {dirty && <p>尚未保存的仓库、分支和令牌填写将被清空。</p>}
    </Modal>
    <Modal title="确认安装更新" open={!!confirmation} onCancel={() => { if (busy !== 'install') setConfirmation(null) }} onOk={() => void install()}
      okText="自动备份并安装" cancelText="取消" confirmLoading={busy === 'install'} okButtonProps={{ disabled: !canInstall || validCheck?.id !== confirmation?.id }} cancelButtonProps={{ disabled: busy === 'install' }} closable={busy !== 'install'} maskClosable={false} keyboard={busy !== 'install'}>
      {confirmation && validCheck?.id !== confirmation.id && <Alert type="warning" message="检查结果已变化，请关闭后重新确认最新版本。" />}
      {confirmation && validCheck?.id === confirmation.id && !checkTrusted(validCheck, data) && <Alert type="warning" message="宿主信任状态已变化，请关闭后重新检查版本。" />}
      {confirmation && validCheck?.id === confirmation.id && checkTrusted(validCheck, data) && <p>{trustedLabel(validCheck)}；安装前宿主还会再次验证。</p>}
      <p>即将安装 {confirmation?.version || '所选版本'}。系统会先自动备份，安装期间网页会短暂不可用。</p>
      <p>请确认其他成员已保存正在填写的内容。完成后，由你刷新页面使用新版本。</p>
    </Modal>
  </div>
}
