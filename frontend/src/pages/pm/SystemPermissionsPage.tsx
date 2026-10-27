import { useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Collapse, Empty, Input, Modal, Radio, Result, Select, Skeleton, Switch, Tag, message } from 'antd'
import { useBlocker } from 'react-router-dom'
import { WorkPageHeader } from '../../components/WorkPage'
import { errMsg } from '../../api/client'
import { permissionsApi, type MemberPermissions, type PermissionCatalog, type PermissionDefinition, type PermissionMember, type PermissionOverrides } from '../../api/permissions'
import { useAuth } from '../../stores/auth'
import { useSubmitLock } from '../../hooks/useSubmitLock'
import './SystemPermissionsPage.css'

type Choice = 'inherit' | 'allow' | 'deny'
const hasOverride = (values: PermissionOverrides, key: string) => Object.prototype.hasOwnProperty.call(values, key)
const choiceFor = (values: PermissionOverrides, key: string): Choice => hasOverride(values, key) ? values[key] ? 'allow' : 'deny' : 'inherit'
const changedKeys = (base: PermissionOverrides, draft: PermissionOverrides) => [...new Set([...Object.keys(base), ...Object.keys(draft)])]
  .filter(key => choiceFor(base, key) !== choiceFor(draft, key))
const memberName = (member: PermissionMember) => member.display_name || member.username
const locked = (permission: PermissionDefinition) => !!permission.admin_locked
const scopes: Record<string, string> = {
  global: '全系统功能', system: '全系统功能', own: '本人范围', project: '可见项目',
  visible_projects: '可见项目', all_projects: '全部普通项目', archives: '历史归档库', visible_people: '人员范围',
}
const risks: Record<string, { name: string; color: string }> = {
  normal: { name: '常规', color: 'default' }, low: { name: '常规', color: 'default' }, medium: { name: '注意影响', color: 'gold' },
  high: { name: '高风险', color: 'orange' }, critical: { name: '敏感操作', color: 'red' },
}

/** Project-context inheritance is conditional, never an unconditional deny. */
function statusFor(permission: PermissionDefinition, policy: MemberPermissions, draft: PermissionOverrides) {
  if (!policy.user.is_active) return { allowed: false, label: '账号停用', source: '设置保留，启用账号后按规则生效', color: 'default' }
  if (policy.user.role === 'readonly' && !permission.read_only) return { allowed: false, label: '只读预设禁止', source: '只读账号不能写入；需在账号设置调整角色', color: 'default' }
  const choice = choiceFor(draft, permission.key)
  if (choice === 'allow') return { allowed: true, label: '允许', source: '单独允许', color: 'green' }
  if (choice === 'deny') return { allowed: false, label: '禁止', source: '单独禁止', color: 'red' }
  if (permission.contextual_default) return { allowed: false, label: '按项目职责/授权', source: '继承项目职责与已有授权', color: 'blue' }
  const allowed = policy.defaults.includes(permission.key)
  return { allowed, label: allowed ? '允许' : '禁止', source: '继承角色默认', color: allowed ? 'green' : 'default' }
}

export default function SystemPermissionsPage() {
  const { user, refreshPermissions } = useAuth()
  const isAdmin = user?.role === 'admin'
  const session = useRef({ id: user?.id, isAdmin })
  session.current = { id: user?.id, isAdmin }
  const [catalog, setCatalog] = useState<PermissionCatalog | null>(null)
  const [members, setMembers] = useState<PermissionMember[]>([])
  const [directoryLoading, setDirectoryLoading] = useState(false)
  const [directoryError, setDirectoryError] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<MemberPermissions | null>(null)
  const detailRef = useRef<MemberPermissions | null>(null)
  const [draft, setDraft] = useState<PermissionOverrides>({})
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState('')
  const [saving, setSaving] = useState(false)
  const savingRef = useRef(false)
  const saveLock = useSubmitLock()
  const [saveError, setSaveError] = useState('')
  const [conflict, setConflict] = useState(false)
  const [latest, setLatest] = useState<MemberPermissions | null>(null)
  const [refreshingLatest, setRefreshingLatest] = useState(false)
  const refreshingLatestRef = useRef(false)
  const [latestError, setLatestError] = useState('')
  const [memberSearch, setMemberSearch] = useState('')
  const [permissionSearch, setPermissionSearch] = useState('')
  const [onlyOverrides, setOnlyOverrides] = useState(false)
  const [onlyAllowed, setOnlyAllowed] = useState(false)
  const [openGroups, setOpenGroups] = useState<string[]>([])
  const directorySequence = useRef(0)
  const detailSequence = useRef(0)
  const dirtyRef = useRef(false)
  const navDialog = useRef<ReturnType<typeof Modal.confirm> | null>(null)
  const memberDialog = useRef<ReturnType<typeof Modal.confirm> | null>(null)
  const dirtyKeys = detail ? changedKeys(detail.overrides, draft) : []
  const dirty = dirtyKeys.length > 0
  dirtyRef.current = dirty
  const blocker = useBlocker(({ currentLocation, nextLocation }) => (dirtyRef.current || savingRef.current) &&
    (currentLocation.pathname !== nextLocation.pathname || currentLocation.search !== nextLocation.search))
  const blockerRef = useRef(blocker)
  blockerRef.current = blocker

  const applyDetail = (data: MemberPermissions) => {
    detailRef.current = data
    setDetail(data); setDraft({ ...data.overrides }); dirtyRef.current = false
    setSaveError(''); setConflict(false); setLatest(null); setLatestError('')
    setMembers(current => current.map(member => member.id === data.user.id ? data.user : member))
  }
  const updateDraft = (values: PermissionOverrides) => {
    dirtyRef.current = !!detailRef.current && changedKeys(detailRef.current.overrides, values).length > 0
    setDraft(values)
    if (!conflict) setSaveError('')
  }

  const loadDirectory = async () => {
    if (!session.current.isAdmin) return
    const actor = session.current.id, sequence = ++directorySequence.current
    setDirectoryLoading(true); setDirectoryError('')
    try {
      const [nextCatalog, nextMembers] = await Promise.all([permissionsApi.catalog(), permissionsApi.users()])
      if (sequence !== directorySequence.current || session.current.id !== actor || !session.current.isAdmin) return
      setCatalog(nextCatalog); setMembers(nextMembers)
      setOpenGroups(current => current.length ? current : nextCatalog.groups.slice(0, 1).map(group => group.key))
    } catch (error) {
      if (sequence === directorySequence.current && session.current.id === actor && session.current.isAdmin) setDirectoryError(errMsg(error))
    } finally {
      if (sequence === directorySequence.current && session.current.id === actor && session.current.isAdmin) setDirectoryLoading(false)
    }
  }

  const loadMember = async (id: string) => {
    const actor = session.current.id, sequence = ++detailSequence.current
    setDetailLoading(true); setDetailError('')
    try {
      const data = await permissionsApi.getUser(id)
      if (sequence !== detailSequence.current || session.current.id !== actor || !session.current.isAdmin) return
      applyDetail(data)
    } catch (error) {
      if (sequence === detailSequence.current && session.current.id === actor && session.current.isAdmin) setDetailError(errMsg(error))
    } finally {
      if (sequence === detailSequence.current && session.current.id === actor && session.current.isAdmin) setDetailLoading(false)
    }
  }

  useEffect(() => {
    directorySequence.current++; detailSequence.current++
    setCatalog(null); setMembers([]); setSelectedId(null); setDetail(null); detailRef.current = null
    setDraft({}); dirtyRef.current = false; setSaveError(''); setConflict(false); setLatest(null)
    setDetailLoading(false); setDetailError(''); setRefreshingLatest(false); refreshingLatestRef.current = false; setLatestError('')
    if (isAdmin) void loadDirectory()
    return () => { directorySequence.current++; detailSequence.current++ }
  }, [isAdmin, user?.id])

  useEffect(() => {
    if (blocker.state !== 'blocked') { navDialog.current?.destroy(); navDialog.current = null; return }
    if (savingRef.current) { message.info('权限正在保存，请等待结果后再离开'); blocker.reset(); return }
    if (navDialog.current) return
    navDialog.current = Modal.confirm({ title: '权限有未保存的修改', content: '继续调整会保留当前设置；放弃后这些修改不会生效。',
      okText: '放弃修改并离开', cancelText: '继续调整',
      onOk: () => {
        setDraft({ ...detailRef.current?.overrides }); dirtyRef.current = false
        if (blockerRef.current.state === 'blocked') blockerRef.current.proceed()
      },
      onCancel: () => { if (blockerRef.current.state === 'blocked') blockerRef.current.reset() },
    })
  }, [blocker])
  useEffect(() => {
    if (!dirty && !saving) return
    const prevent = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', prevent)
    return () => window.removeEventListener('beforeunload', prevent)
  }, [dirty, saving])
  useEffect(() => () => { navDialog.current?.destroy(); memberDialog.current?.destroy() }, [])

  const switchMember = (id: string) => {
    if (id === selectedId || savingRef.current || refreshingLatestRef.current) return
    const proceed = () => {
      detailSequence.current++; setSelectedId(id); setDetail(null); detailRef.current = null
      setDraft({}); dirtyRef.current = false; setDetailError(''); setSaveError(''); setConflict(false); setLatest(null)
      setPermissionSearch(''); setOnlyOverrides(false); setOnlyAllowed(false)
      void loadMember(id)
    }
    if (!dirtyRef.current) { proceed(); return }
    if (memberDialog.current) return
    memberDialog.current = Modal.confirm({ title: '当前成员的权限有未保存修改', content: '切换成员前，请先保存或明确放弃当前修改。',
      okText: '放弃修改并切换', cancelText: '继续调整',
      onOk: () => { memberDialog.current = null; proceed() }, onCancel: () => { memberDialog.current = null },
    })
  }

  const save = async (policy = detail, values = draft) => {
    if (!policy || !session.current.isAdmin || !saveLock.tryAcquire()) return
    const actor = session.current.id, sequence = detailSequence.current
    setSaving(true); savingRef.current = true; setSaveError('')
    try {
      const data = await permissionsApi.updateUser(policy.user.id, { version: policy.version, overrides: { ...values } })
      if (sequence !== detailSequence.current || session.current.id !== actor || !session.current.isAdmin) return
      applyDetail(data)
      message.success(`${memberName(data.user)}的权限已保存`)
      // The silent auth refresh updates available actions without unmounting
      // this saved policy editor or changing offline-account ownership.
      if (data.user.id === actor) void refreshPermissions().catch(() => message.info('权限已保存，请刷新登录状态以更新入口'))
    } catch (error: any) {
      if (sequence !== detailSequence.current || session.current.id !== actor || !session.current.isAdmin) return
      setSaveError(errMsg(error))
      if (error.response?.status === 409) { setConflict(true); setLatest(null) }
    } finally { savingRef.current = false; setSaving(false); saveLock.release() }
  }

  const readLatest = async () => {
    if (!detail || savingRef.current || refreshingLatestRef.current) return
    const id = detail.user.id, actor = session.current.id, sequence = detailSequence.current
    refreshingLatestRef.current = true; setRefreshingLatest(true); setLatest(null); setLatestError('')
    try {
      const data = await permissionsApi.getUser(id)
      if (sequence === detailSequence.current && session.current.id === actor && session.current.isAdmin) setLatest(data)
    } catch (error) {
      if (sequence === detailSequence.current && session.current.id === actor && session.current.isAdmin) setLatestError(errMsg(error))
    } finally {
      if (sequence === detailSequence.current) { refreshingLatestRef.current = false; setRefreshingLatest(false) }
    }
  }

  const retryWithLatest = () => {
    if (!detail || !latest || savingRef.current || !catalog) return
    const definitions = catalog.groups.flatMap(group => group.permissions)
    const keys = changedKeys(detail.overrides, draft)
    if (keys.some(key => definitions.some(permission => permission.key === key && locked(permission)))) {
      setLatestError('部分修改涉及不可委派或关闭的权限管理入口；请使用最新权限后重新核对其他设置。')
      return
    }
    const merged = { ...latest.overrides }
    for (const key of keys) { if (hasOverride(draft, key)) merged[key] = draft[key]; else delete merged[key] }
    const fresh = latest
    detailRef.current = fresh; setDetail(fresh); setLatest(null); setConflict(false)
    updateDraft(merged)
    void save(fresh, merged)
  }

  const roleName = (role: string) => catalog?.roles.find(item => item.key === role)?.name ?? role
  const query = memberSearch.trim().toLocaleLowerCase()
  const visibleMembers = members.filter(member => [memberName(member), member.username, roleName(member.role)].some(text => text.toLocaleLowerCase().includes(query)))
  const permissionQuery = permissionSearch.trim().toLocaleLowerCase()
  const shownGroups = useMemo(() => !catalog || !detail ? [] : catalog.groups.map(group => ({ ...group,
    visible: group.permissions.filter(permission => (!permissionQuery || [group.name, permission.name, permission.description, permission.key].some(text => text.toLocaleLowerCase().includes(permissionQuery))) &&
      (!onlyOverrides || hasOverride(draft, permission.key)) && (!onlyAllowed || statusFor(permission, detail, draft).allowed)),
  })).filter(group => group.visible.length), [catalog, detail, draft, permissionQuery, onlyOverrides, onlyAllowed])
  const activeGroups = permissionQuery || onlyOverrides || onlyAllowed ? shownGroups.map(group => group.key) : openGroups
  const editDisabled = saving || detailLoading || refreshingLatest || !isAdmin
  const writeChoices = (permissions: PermissionDefinition[], choice: Choice) => {
    if (!detail || editDisabled) return
    const next = { ...draft }
    for (const permission of permissions) {
      if (locked(permission)) continue
      if (choice === 'inherit') delete next[permission.key]
      else next[permission.key] = choice === 'allow'
    }
    updateDraft(next)
  }

  if (!isAdmin) return <Result status="403" title="只有系统管理员可管理系统权限" subTitle="项目内授权请使用项目中的人员与协管设置。" />

  return <div className="system-permissions-page">
    <WorkPageHeader title="系统权限" description="先选择成员，再按功能模块调整。继承使用默认规则，允许和禁止是该成员的单独设置。"
      tools={<Button disabled={saving || refreshingLatest || directoryLoading} onClick={() => void loadDirectory()}>刷新成员与目录</Button>} />
    <div className="permissions-scope-note"><strong>权限与项目范围是两回事</strong><p>项目内操作只作用于该成员可见的项目，不会让他看到不相关项目。继承的项目权限按具体项目职责或已有授权判断；组织全部项目可见属于单独的敏感权限。</p></div>
    {directoryError && <Alert type="error" showIcon message="暂时无法加载权限目录" description={directoryError} action={<Button onClick={() => void loadDirectory()}>重新加载目录</Button>} />}
    {directoryLoading && !catalog ? <Skeleton active paragraph={{ rows: 6 }} /> : catalog && <div className="permissions-workspace">
      <aside className="permissions-members" aria-label="成员列表">
        <h2>选择成员 <small>{members.length} 位</small></h2>
        <Input.Search aria-label="搜索成员" placeholder="姓名、账号或角色" allowClear value={memberSearch} onChange={event => setMemberSearch(event.target.value)} disabled={saving} />
        <div className="permissions-member-list">
          {visibleMembers.map(member => <button key={member.id} type="button" className={`permissions-member${member.id === selectedId ? ' is-selected' : ''}`} aria-label={`选择成员：${memberName(member)}`} aria-pressed={member.id === selectedId} disabled={saving || refreshingLatest} onClick={() => switchMember(member.id)}>
            <span><strong>{memberName(member)}</strong><small>{member.username}</small></span><span className="permissions-member-meta">{roleName(member.role)}{!member.is_active && <Tag>已停用</Tag>}</span>
          </button>)}
          {!visibleMembers.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={members.length ? '没有匹配的成员' : '暂无成员'} />}
        </div>
      </aside>
      <main className="permissions-editor">
        <div className="permissions-mobile-member"><label>选择成员<Select aria-label="选择成员" popupClassName="permissions-member-popup" showSearch optionFilterProp="label" placeholder="选择要调整的成员" value={selectedId} disabled={saving || refreshingLatest} onChange={switchMember} options={members.map(member => ({ value: member.id, label: `${memberName(member)} · ${roleName(member.role)}${member.is_active ? '' : ' · 已停用'}` }))} /></label></div>
        {detailLoading ? <Skeleton active paragraph={{ rows: 6 }} /> : detailError ? <Alert type="error" showIcon message="暂时无法读取该成员权限" description={detailError} action={<Button onClick={() => selectedId && void loadMember(selectedId)}>重新读取权限</Button>} /> : !detail ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择一位成员，查看默认权限并按模块调整。" /> : <>
          <div className="permissions-member-heading"><div><h2>{memberName(detail.user)}</h2><p>{detail.user.username} · {roleName(detail.user.role)}</p></div><div><Tag color="blue">{roleName(detail.user.role)}默认</Tag>{!detail.user.is_active && <Tag>账号已停用</Tag>}<Tag>{Object.keys(draft).length} 项单独设置</Tag></div></div>
          <details className="permissions-advanced"><summary>高级：逐项权限设置</summary>
          <div className="permissions-filters">
            <Input.Search aria-label="搜索权限" placeholder="功能、说明或权限代码" allowClear value={permissionSearch} onChange={event => setPermissionSearch(event.target.value)} />
            <label><Switch checked={onlyOverrides} onChange={setOnlyOverrides} aria-label="仅看已调整" />仅看已调整</label>
            <label><Switch checked={onlyAllowed} onChange={setOnlyAllowed} aria-label="仅看已允许" />仅看已允许</label>
            <Button onClick={() => setOpenGroups(current => current.length === catalog.groups.length ? [] : catalog.groups.map(group => group.key))}>展开 / 收起全部</Button>
          </div>
          <p className="permissions-filter-note">“已调整”指单独设置的权限；项目继承项按项目职责判定，不列为无条件允许。</p>
          {saveError && <Alert className="permissions-save-error" showIcon type={conflict ? 'warning' : 'error'} message={conflict ? '权限已被他人更新，本次修改仍保留' : '未能保存，本次修改仍保留'} description={saveError}
            action={conflict ? <Button disabled={saving} loading={refreshingLatest} onClick={() => void readLatest()}>读取最新权限</Button> : undefined} />}
          {conflict && latest && <div className="permissions-conflict"><strong>已读取最新版本，尚未替换你的输入</strong><p>保留并重试只覆盖你本次调整的权限；其他人的新设置会保留。</p><Button disabled={saving} onClick={retryWithLatest}>保留本次调整并重试</Button><Button disabled={saving} onClick={() => applyDetail(latest)}>使用最新权限，放弃本次修改</Button></div>}
          {latestError && <Alert type="error" showIcon message="无法继续使用最新版本" description={latestError} />}
          {shownGroups.length ? <Collapse className="permissions-modules" bordered={false} activeKey={activeGroups} onChange={keys => setOpenGroups(typeof keys === 'string' ? [keys] : keys)} items={shownGroups.map(group => {
            const editable = group.visible.filter(permission => !locked(permission))
            const allowed = group.permissions.filter(permission => statusFor(permission, detail, draft).allowed).length
            const contextual = group.permissions.filter(permission => permission.contextual_default && choiceFor(draft, permission.key) === 'inherit').length
            return { key: group.key, label: <div className="permissions-module-title"><strong>{group.name}</strong><span>{group.permissions.length} 项 · {allowed} {dirty ? '拟允许' : '允许'} · {group.permissions.filter(permission => hasOverride(draft, permission.key)).length} 已调整{contextual ? ` · ${contextual} 按项目职责` : ''}</span></div>, children: <>
              <p className="permissions-module-description">{group.description}</p>
              {group.key === 'organization' && <p className="permissions-module-description">模板页内容需要“使用任务模板”允许，查看与维护分别控制入口和修改。</p>}
              <div className="permissions-batch"><span>本组当前显示 {editable.length} 项可调整</span><div><Button disabled={editDisabled || !editable.length} onClick={() => writeChoices(group.visible, 'inherit')}>本组继承</Button><Button disabled={editDisabled || !editable.length} onClick={() => writeChoices(group.visible, 'allow')}>本组允许</Button><Button disabled={editDisabled || !editable.length} onClick={() => writeChoices(group.visible, 'deny')}>本组禁止</Button></div></div>
              {group.visible.map(permission => {
                const effective = statusFor(permission, detail, draft), saved = latest ?? detail,
                  current = statusFor(permission, saved, saved.overrides), protectedEntry = locked(permission), risk = risks[permission.risk]
                return <section className="permissions-row" key={permission.key} aria-label={`权限：${permission.name}`}>
                  <div className="permissions-copy"><h3>{permission.name}</h3><div className="permissions-row-tags"><Tag>{scopes[permission.scope] ?? permission.scope}</Tag>{risk && !['low', 'normal'].includes(permission.risk) && <Tag color={risk.color}>{risk.name}</Tag>}{protectedEntry && <Tag color="purple">{detail.user.role === 'admin' ? '保留管理员入口' : '仅管理员身份'}</Tag>}</div><p>{permission.description}</p><small>{permission.contextual_default ? '默认：按项目职责与已有授权' : `默认角色：${permission.default_roles.length ? permission.default_roles.map(roleName).join('、') : '无'}`}</small></div>
                  <div className="permissions-choice"><div role="radiogroup" aria-label={`${permission.name}权限设置`}><Radio.Group name={`permission-${permission.key}`} value={choiceFor(draft, permission.key)} disabled={editDisabled || protectedEntry || (detail.user.role === 'readonly' && !permission.read_only)} onChange={event => writeChoices([permission], event.target.value)} optionType="button" buttonStyle="solid" options={[{ value: 'inherit', label: '继承' }, { value: 'allow', label: '允许' }, { value: 'deny', label: '禁止' }]} /></div>
                    <div className="permissions-effective"><Tag color={current.color}>{conflict && !latest ? '更新前' : '当前'}：{current.label}</Tag><span>{current.source}</span></div>
                    {dirtyKeys.includes(permission.key) && <div className="permissions-effective permissions-preview"><Tag color={effective.color}>保存后：{effective.label}</Tag><span>{effective.source}</span></div>}
                    {protectedEntry && <small>权限管理仅限真实管理员身份，不能单独委派或关闭。</small>}
                  </div>
                </section>
              })}
            </> }
          })} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的权限"><Button onClick={() => { setPermissionSearch(''); setOnlyOverrides(false); setOnlyAllowed(false) }}>清除筛选</Button></Empty>}
          <div className={`permissions-save-bar${dirty ? ' is-dirty' : ''}`} role="region" aria-label="权限保存操作">
            <div><strong>{dirty ? `${dirtyKeys.length} 项未保存修改` : conflict ? '本次修改已取消，需核对最新权限' : '当前设置已保存'}</strong><small>{saving ? '正在保存，请等待结果后再切换成员或离开。' : dirty ? '保存后才会生效；取消修改不会改变已保存权限。' : conflict ? '权限已被他人更新，请读取最新版本后继续。' : '调整功能时可以随时切换继承、允许或禁止。'}</small></div>
            <div><Button disabled={!dirty || saving || refreshingLatest} onClick={() => {
              if (latest) { applyDetail(latest); return }
              updateDraft({ ...detail.overrides })
              if (!conflict) { setSaveError(''); setLatestError('') }
            }}>取消修改</Button><Button type="primary" loading={saving} disabled={!dirty || conflict || refreshingLatest} onClick={() => void save()}>保存权限</Button></div>
          </div>
          </details>
        </>}
      </main>
    </div>}
  </div>
}
