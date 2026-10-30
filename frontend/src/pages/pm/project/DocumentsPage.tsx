import { PROJECT_EVENT_LABELS } from '../../../constants/projectEvents'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Collapse, Drawer, Dropdown, Empty, Input, Modal, Popconfirm, Segmented, Select, Space, Switch, Table, Tabs, Tag, Tooltip, Typography, message } from 'antd'
import { DownOutlined, DownloadOutlined, EllipsisOutlined, PlusOutlined, UploadOutlined } from '@ant-design/icons'
import { useLocation } from 'react-router-dom'
import { projectDocumentsApi, downloadDocumentResource, downloadSelectedDocuments, type ProjectDocument, type ProjectDocumentDefinition, type ProjectDocumentsResponse, type ProjectDocumentVersion, type ProjectFile } from '../../../api/projectDocuments'
import { errMsg } from '../../../api/client'
import { isUploadQueued } from '../../../uploads/types'
import { UPLOAD_COMPLETE_EVENT } from '../../../uploads/queue'
import { useAuth } from '../../../stores/auth'
import { hasSystemPermission } from '../../../constants/systemPermissions'
import { DOCUMENT_STAGES, documentRuleLabel } from '../../../constants/documentRules'
import { useProjectCapability, useProjectWriteBlocked } from '../../../hooks/useProjectCapability'
import { useMediaQuery } from '../../../hooks/useMediaQuery'
import { MEDIA_QUERY } from '../../../constants/breakpoints'
import { formatDateTime, parseDateTime } from '../../../utils/date'
import { deadlineLabel, basisLabel } from '../../../utils/documentDeadlines'
import { useUnsavedNavigation } from '../../../hooks/useUnsavedNavigation'
import { WorkPageHeader, WorkSection } from '../../../components/WorkPage'
import { InfoHint } from '../../../components/IconAction'
import ProjectDocumentRequirementEditor from './ProjectDocumentRequirementEditor'
import ProjectStoragePanel from '../../../components/ProjectStoragePanel'
import DocumentConfidentialityModal, { type ConfidentialityTarget } from './DocumentConfidentialityModal'
import ProcurementPanel from './ProcurementPanel'
import AcceptanceRecordsPanel from './AcceptanceRecordsPanel'
import EntryReviewPanel from './EntryReviewPanel'
import GeneratedFormControl from './GeneratedFormControl'
import './FieldWorkPages.css'
import './DocumentsPage.css'

const stageName = (key: string) => DOCUMENT_STAGES.find(stage => stage.value === key)?.label ?? '历史待分类'
const sizeLabel = (bytes: number) => bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.ceil(bytes / 1024))} KB`
const statusName = { pending: '待提交', submitted: '已提交', waived: '不适用' }
const reviewName: Record<string, string> = { approved: '审核通过', rejected: '已退回', submitted: '原记录已提交', pending: '待核对' }
function late(row: ProjectDocument) { return row.status === 'pending' && row.applicable !== false && !row.due_is_estimated && !!row.due_at && parseDateTime(row.due_at).isBefore(new Date()) }
function rowName(row: ProjectDocument) { return `${row.code} ${row.name}${row.vehicle_label ? ` · ${row.vehicle_label}` : ''}${row.period_key ? ` · ${row.period_key}` : ''}` }

function ReviewTrail({ metadata }: { metadata: Record<string, unknown> }) {
  const history = Array.isArray(metadata.review_history) ? metadata.review_history.filter((value): value is Record<string, unknown> => !!value && typeof value === 'object') : []
  const latest = metadata.latest_review && typeof metadata.latest_review === 'object' ? metadata.latest_review as Record<string, unknown> : metadata
  const line = (record: Record<string, unknown>) => <><span>{reviewName[String(record.decision ?? record.status)] || '原审核信息保留'}</span>{typeof record.note === 'string' && `：${record.note}`}{typeof record.reject_reason === 'string' && `：${record.reject_reason}`}{typeof record.at === 'string' && <small> · {typeof record.by_name === 'string' && record.by_name ? record.by_name : '原审核人未记录'} · {formatDateTime(record.at)}</small>}</>
  return <><Typography.Paragraph type="secondary">{line(latest)}</Typography.Paragraph>{history.length > 1 && <details><summary>审核历史（{history.length}）</summary>{history.map((record, index) => <Typography.Paragraph key={index}>{line(record)}</Typography.Paragraph>)}</details>}</>
}

export default function DocumentsPage({ projectId, templateId, onProjectChange }: { projectId: string; templateId?: string; onProjectChange?: () => void }) {
  const { user } = useAuth()
  const location = useLocation()
  const mobile = useMediaQuery(MEDIA_QUERY.mobile)
  const writeBlocked = useProjectWriteBlocked()
  const manageCapability = useProjectCapability('project.manage_plan')
  const deleteCapability = useProjectCapability('project.update')
  const exportCapability = useProjectCapability('project.export')
  const [data, setData] = useState<ProjectDocumentsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [actionError, setActionError] = useState('')
  const [busy, setBusy] = useState(false)
  const [search, setSearch] = useState('')
  const [stage, setStage] = useState<string>()
  const [status, setStatus] = useState('all')
  const [vehicle, setVehicle] = useState<string>()
  const [selected, setSelected] = useState<string[]>([])
  const [editing, setEditing] = useState<ProjectDocumentDefinition | 'new' | null>(null)
  const [requirementDirty, setRequirementDirty] = useState(false)
  const [procurementDirty, setProcurementDirty] = useState(false)
  const [acceptanceDirty, setAcceptanceDirty] = useState(false)
  const [entryDirty, setEntryDirty] = useState(false)
  const [confidentialityDirty, setConfidentialityDirty] = useState(false)
  const [confidentialityTarget, setConfidentialityTarget] = useState<ConfidentialityTarget | null>(null)
  const [procurementOpen, setProcurementOpen] = useState(false)
  const [acceptanceOpen, setAcceptanceOpen] = useState(false)
  const [entryOpen, setEntryOpen] = useState(false)
  const [ownerEditing, setOwnerEditing] = useState<ProjectDocument | null>(null)
  const [ownerId, setOwnerId] = useState<string | undefined>()
  const [historyId, setHistoryId] = useState<string | null>(null)
  const [statusChange, setStatusChange] = useState<{ row: ProjectDocument; status: 'pending' | 'waived' } | null>(null)
  const [reason, setReason] = useState('')
  const [review, setReview] = useState<{ documentId: string; versionId: string; decision: 'approved' | 'rejected' } | null>(null)
  const [reviewNote, setReviewNote] = useState('')
  const [uploadOpen, setUploadOpen] = useState(false)
  const [uploadEpoch, setUploadEpoch] = useState(0)
  const [uploadMode, setUploadMode] = useState<'upload' | 'existing'>('upload')
  const [uploadIds, setUploadIds] = useState<string[]>([])
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploadNote, setUploadNote] = useState('')
  const [signatureDates, setSignatureDates] = useState<Record<string, string>>({})
  const [uploadError, setUploadError] = useState('')
  const [uploadConfidential, setUploadConfidential] = useState(false)
  const [uploadPeople, setUploadPeople] = useState<string[]>([])
  const [uploadMembers, setUploadMembers] = useState<{ id: string; display_name: string }[]>([])
  const [uploadPeopleLoading, setUploadPeopleLoading] = useState(false)
  const [uploadPeopleError, setUploadPeopleError] = useState('')
  const [existingFileId, setExistingFileId] = useState<string>()
  const [existingFiles, setExistingFiles] = useState<ProjectFile[]>([])
  const [filesLoading, setFilesLoading] = useState(false)
  const [filesError, setFilesError] = useState('')
  const active = useRef(projectId); active.current = projectId
  const sequence = useRef(0)
  const fileSequence = useRef(0)
  const generation = useRef(0)
  const mutation = useRef(false)
  const [, setNavigationDirty] = useUnsavedNavigation({ title: '资料有尚未保存的修改' })
  const documents = data?.documents ?? []
  const definitions = data?.definitions ?? []
  const canExport = exportCapability && user?.permission_overrides?.['project.export'] !== false && !loadError && !loading
  const canSubmit = !!data?.permissions.submit && hasSystemPermission(user, 'worker.deliver') && !writeBlocked && !loadError
  const canManage = !!data?.permissions.manage && manageCapability && !writeBlocked && !loadError
  const canManageConfidentiality = data?.permissions.manage_confidentiality === true && canManage && !loading
  const canDeleteFile = deleteCapability && !writeBlocked && !loadError
  const load = useCallback(async () => {
    const ticket = ++sequence.current
    setLoading(true); setLoadError('')
    try {
      const response = await projectDocumentsApi.list(projectId)
      if (!Array.isArray(response.documents) || !Array.isArray(response.definitions) || !Array.isArray(response.unclassified_files) || !response.permissions) throw new Error('资料响应不完整')
      if (ticket !== sequence.current || active.current !== projectId) return
      setData(response)
      setSelected(previous => previous.filter(id => response.documents.some(row => row.id === id)))
    } catch (failure) { if (ticket === sequence.current) setLoadError(errMsg(failure)) }
    finally { if (ticket === sequence.current) setLoading(false) }
  }, [projectId])
  useEffect(() => {
    setData(null); setSearch(''); setStatus('all'); setStage(undefined); setVehicle(undefined); setSelected([]); setActionError('')
    setEditing(null); setOwnerEditing(null); setHistoryId(null); setStatusChange(null); setReview(null); setUploadOpen(false); setUploadFile(null); setUploadNote(''); setSignatureDates({}); setExistingFileId(undefined)
    setConfidentialityTarget(null); setConfidentialityDirty(false)
    setProcurementOpen(false); setAcceptanceOpen(false); setEntryOpen(false); setRequirementDirty(false); setProcurementDirty(false); setAcceptanceDirty(false); setEntryDirty(false)
    mutation.current = false; setBusy(false); void load()
    return () => { sequence.current++; fileSequence.current++; generation.current++ }
  }, [projectId, user?.id, load])
  useEffect(() => { const refresh = () => { void load(); onProjectChange?.() }; window.addEventListener(UPLOAD_COMPLETE_EVENT, refresh); return () => window.removeEventListener(UPLOAD_COMPLETE_EVENT, refresh) }, [load, onProjectChange])
  const policyVersion = useRef(user?.permission_version)
  useEffect(() => { if (policyVersion.current !== user?.permission_version) { policyVersion.current = user?.permission_version; void load() } }, [user?.permission_version, load])
  useEffect(() => { setNavigationDirty(requirementDirty || procurementDirty || acceptanceDirty || entryDirty || confidentialityDirty || (uploadOpen && (!!uploadFile || !!existingFileId || !!uploadNote.trim() || uploadConfidential || Object.values(signatureDates).some(Boolean)))) }, [requirementDirty, procurementDirty, acceptanceDirty, entryDirty, confidentialityDirty, uploadOpen, uploadFile, existingFileId, uploadNote, uploadConfidential, signatureDates, setNavigationDirty])
  useEffect(() => {
    let current = true
    if (!uploadOpen || !uploadConfidential) { setUploadPeopleLoading(false); return }
    if (!canManageConfidentiality) { setUploadPeopleLoading(false); if (!loading) setUploadPeopleError('保密设置权限已变化，请取消后重新核对'); return }
    setUploadPeopleLoading(true); setUploadPeopleError('')
    projectDocumentsApi.confidentialityMembers(projectId).then(rows => {
      if (!Array.isArray(rows)) throw new Error('人员列表无法读取')
      if (current) setUploadMembers(rows)
    }).catch(failure => { if (current) setUploadPeopleError(errMsg(failure)) })
      .finally(() => { if (current) setUploadPeopleLoading(false) })
    return () => { current = false }
  }, [uploadOpen, uploadConfidential, canManageConfidentiality, loading, projectId])
  useEffect(() => { const query = new URLSearchParams(location.search); setVehicle(query.get('vehicle') || undefined); setSelected([]); if (query.get('procurements') === '1') setProcurementOpen(true); if (query.get('acceptance') === '1') setAcceptanceOpen(true); if (query.get('review') === '1') setEntryOpen(true); if (query.get('filter') === 'week') setStatus('week'); const targetStage = query.get('stage'); if (DOCUMENT_STAGES.some(item => item.value === targetStage)) setStage(targetStage!) }, [location.search, projectId])
  useEffect(() => { const id = new URLSearchParams(location.search).get('document'); if (id && documents.some(row => row.id === id)) setHistoryId(id) }, [location.search, data])

  const act = async (operation: () => Promise<unknown>, success: string) => {
    if (mutation.current || writeBlocked || loadError) return false
    const ticket = generation.current
    mutation.current = true; setBusy(true); setActionError('')
    try {
      await operation()
      if (ticket !== generation.current) return false
      message.success(success); await load(); onProjectChange?.(); return true
    } catch (failure) {
      if (ticket !== generation.current) return false
      if (isUploadQueued(failure)) { message.info(failure.message); return true }
      setActionError(errMsg(failure)); return false
    }
    finally { if (ticket === generation.current) { mutation.current = false; setBusy(false) } }
  }
  const download = async (path: string, name: string) => {
    try { await downloadDocumentResource(path, name) } catch (failure) { setActionError(errMsg(failure)) }
  }
  const getFiles = async () => {
    const ticket = ++fileSequence.current
    setFilesLoading(true); setFilesError('')
    try { const files = await projectDocumentsApi.files(projectId); if (ticket === fileSequence.current && active.current === projectId) setExistingFiles(files) }
    catch (failure) { if (ticket === fileSequence.current) setFilesError(errMsg(failure)) }
    finally { if (ticket === fileSequence.current) setFilesLoading(false) }
  }
  const openUpload = (ids: string[] = selected, file?: ProjectFile) => {
    setUploadEpoch(value => value + 1); setUploadIds(ids); setUploadMode(file ? 'existing' : 'upload'); setUploadFile(null)
    setUploadNote(''); setSignatureDates({}); setUploadError(''); setExistingFileId(file?.id); setExistingFiles(file ? [file] : [])
    setUploadConfidential(false); setUploadPeople([]); setUploadMembers([]); setUploadPeopleError('')
    setFilesError(''); setUploadOpen(true); if (file) void getFiles()
  }
  const signatureKeys = [...new Set(documents.filter(row => uploadIds.includes(row.id) && row.scope === 'project' && ['after_event','after_milestone'].includes(row.timing_type) && row.timing_event && ['internal_kickoff','delivery_signed','commissioning_done','go_live','training_done','acceptance','handover'].includes(row.timing_event)).map(row => row.timing_event!))]
  const submitUpload = async () => {
    if (!canSubmit || mutation.current) return
    if (uploadMode === 'upload' && !uploadFile) { setUploadError('请选择实际文件，不能空提交'); return }
    if (uploadMode === 'upload' && uploadConfidential && (!canManageConfidentiality || uploadPeopleLoading || uploadPeopleError)) { setUploadError('附件保密范围尚未核对，未上传文件'); return }
    if (uploadMode === 'existing' && (!existingFileId || !uploadIds.length)) { setUploadError('请选择文件及至少一项资料要求'); return }
    const ticket = generation.current
    const milestoneDates = Object.fromEntries(Object.entries(signatureDates).filter(([key,value]) => value && signatureKeys.includes(key)))
    const ok = await act(() => uploadMode === 'upload'
      ? projectDocumentsApi.upload(projectId, { file: uploadFile!, documentIds: uploadIds, note: uploadNote, ...(uploadConfidential ? { confidential: true, confidentialUserIds: uploadPeople } : {}), ...(Object.keys(milestoneDates).length ? { milestoneDates } : {}) })
      : (Object.keys(milestoneDates).length ? projectDocumentsApi.submit(projectId, uploadIds, existingFileId!, uploadNote, milestoneDates) : projectDocumentsApi.submit(projectId, uploadIds, existingFileId!, uploadNote)), uploadIds.length ? '资料已提交，新版本已保存' : '文件已上传，可稍后关联资料要求')
    if (ok && ticket === generation.current) { setUploadOpen(false); setUploadFile(null); setExistingFileId(undefined); setUploadNote(''); setSelected([]) }
  }
  const query = search.trim().toLocaleLowerCase()
  const triggerFilter = new URLSearchParams(location.search).get('trigger')
  const stageFiltered = useMemo(() => documents.filter(row => (!vehicle || row.vehicle_unit_id === vehicle)
    && (!triggerFilter || row.trigger_ref===triggerFilter)
    && (status === 'all' || (status === 'overdue' ? late(row) : status === 'week' ? !!data?.document_actions?.this_week.some(item => item.id === row.id) : status === 'on_demand' ? row.timing_type === 'on_demand' && row.status === 'pending' && row.stage_key !== 'legacy' : row.status === status))
    && `${row.code} ${row.name} ${row.vehicle_label} ${row.period_key ?? ''}`.toLocaleLowerCase().includes(query)), [data, vehicle, status, query,triggerFilter])
  // One stage at a time: default to the first stage that still has pending items; any search or filter shows all stages.
  const stageGroups = useMemo(() => [...DOCUMENT_STAGES.map(item => item.value), 'legacy'].map(key => ({ key, rows: stageFiltered.filter(row => row.stage_key === key) })).filter(group => group.rows.length), [stageFiltered])
  const narrowed = !!query || status !== 'all' || !!vehicle || !!triggerFilter
  const activeStage = stage && (stage === 'all' || stageGroups.some(group => group.key === stage)) ? stage
    : narrowed ? 'all' : stageGroups.find(group => group.rows.some(row => row.status === 'pending' && row.applicable !== false))?.key ?? stageGroups[0]?.key ?? 'all'
  const visible = activeStage === 'all' ? stageFiltered : stageFiltered.filter(row => row.stage_key === activeStage)
  const grouped = activeStage === 'all' ? stageGroups : stageGroups.filter(group => group.key === activeStage)
  const history = documents.find(row => row.id === historyId)
  const current = documents.filter(row => row.applicable !== false && row.stage_key !== 'legacy')
  const waiting = definitions.filter(row => row.waiting_reason)
  const vehicleOptions = [...new Map(documents.filter(row => row.vehicle_unit_id).map(row => [row.vehicle_unit_id!, { value: row.vehicle_unit_id!, label: row.vehicle_label || '车号待补录' }])).values()]
  const renderActions = (row: ProjectDocument) => {
    const more = [
      ...(canManage ? [{ key: 'owner', label: '指派负责人', disabled: busy || loading, onClick: () => { setOwnerEditing(row); setOwnerId(row.owner_id ?? undefined) } }] : []),
      { key: 'history', label: `版本记录 ${row.versions.length}`, onClick: () => setHistoryId(row.id) },
      ...(row.blank_file_id && row.definition_id ? [{ key: 'blank', label: '下载空白模板', onClick: () => void download(`/projects/${encodeURIComponent(projectId)}/documents/requirements/${encodeURIComponent(row.definition_id!)}/blank-file`, `${row.name}空白模板`) }] : []),
      ...(row.code === '4.4' ? [{ key: 'procurement', label: '采购明细', onClick: () => setProcurementOpen(true) }] : []),
      ...(row.code === '7.1' ? [{ key: 'acceptance', label: '验收记录', onClick: () => setAcceptanceOpen(true) }] : []),
      ...(canManageConfidentiality ? [{ key: 'confidential', label: '保密范围', disabled: busy, onClick: () => setConfidentialityTarget({ kind: 'document', row }) }] : []),
      ...(canSubmit && row.applicable !== false ? [{ key: 'waive', label: row.status === 'waived' ? '恢复待提交' : '不适用', disabled: busy || loading, onClick: () => { setReason(''); setStatusChange({ row, status: row.status === 'waived' ? 'pending' : 'waived' }) } }] : []),
      ...(canSubmit && row.status === 'submitted' ? [{ key: 'withdraw', label: '撤回提交', disabled: busy || loading, onClick: () => { setReason(''); setStatusChange({ row, status: 'pending' }) } }] : []),
    ]
    return <Space size={4} wrap className="documents-row-actions">
      {canSubmit && row.applicable !== false && <Button size="small" type={row.status === 'submitted' ? 'default' : 'primary'} ghost={row.status !== 'submitted'} disabled={busy || loading} onClick={() => openUpload([row.id])}>{row.status === 'submitted' ? '提交新版本' : '提交文件'}</Button>}
    {canSubmit && row.applicable !== false && row.scope === 'project' && row.stage_key !== 'legacy' && <>
      {row.code === '6.2' && row.timing_type === 'weekly' && row.period_key === data?.document_actions?.period_key && <GeneratedFormControl projectId={projectId} documentId={row.id} kind="lifecycle" busy={busy || loading} canManageConfidentiality={canManageConfidentiality} generationError={actionError}
        onGenerate={options => act(() => projectDocumentsApi.generateLifecycle(projectId, row.id, options), '本周生命周期表已生成并提交')} />}
      {row.code === '6.9.3' && row.timing_type === 'on_demand' && <GeneratedFormControl projectId={projectId} documentId={row.id} kind="contact" busy={busy || loading} canManageConfidentiality={canManageConfidentiality} generationError={actionError}
        onGenerate={options => act(() => projectDocumentsApi.generateContact(projectId, row.id, options.applicationId!, options), '内部联系单已生成并提交')} />}
      {row.code === '9.2' && row.timing_type === 'lifetime' && <GeneratedFormControl projectId={projectId} documentId={row.id} kind="inventory" busy={busy || loading} canManageConfidentiality={canManageConfidentiality} generationError={actionError}
        onGenerate={options => act(() => projectDocumentsApi.generateInventory(projectId, row.id, options.note ?? '', options), '物资收发清单已生成并提交')} />}
    </>}
      <Dropdown trigger={['click']} menu={{ items: more }}><Button size="small" icon={<EllipsisOutlined />} aria-label={`${row.code} ${row.name}的更多操作`} /></Dropdown>
    </Space>
  }
  const renderState = (row: ProjectDocument) => <><Tag color={row.status === 'submitted' ? 'green' : late(row) ? 'red' : 'default'}>{late(row) ? '已逾期' : statusName[row.status]}</Tag>
    {row.due_state === 'estimated_past_due' && <Tag color="gold">预计截止已过</Tag>}
    {!row.required && <Tag>可选</Tag>}{row.confidential && <Tag color="orange">保密</Tag>}{row.applicable === false && <Tag>原平台资料，保留历史</Tag>}
    {row.status === 'waived' && <div className="documents-note">理由：{row.waived_reason}</div>}</>
  const renderFile = (row: ProjectDocument) => row.latest_version ? <><Button type="link" size="small" disabled={row.latest_version.storage_state === 'removed_by_policy'} onClick={() => void download(row.latest_version!.download_url, row.latest_version!.filename)}>{row.latest_version.filename}</Button>{row.latest_version.storage_state === 'removed_by_policy' && <Tag>原件已按策略清理</Tag>}<div className="documents-note">{row.latest_version.uploaded_by_name || '原提交人未记录'} · {formatDateTime(row.latest_version.uploaded_at)}</div></> : <Typography.Text type="secondary" title={row.source_metadata ? '原记录已保留' : '尚无提交文件'}>—</Typography.Text>
  const closePanel = (dirty: boolean, close: () => void, clear: () => void) => {
    if (busy) return
    const finish = () => { clear(); close() }
    if (dirty) Modal.confirm({ title: '还有未保存的填写内容', content: '关闭后将放弃当前填写。', okText: '放弃并关闭', cancelText: '继续填写', onOk: finish })
    else finish()
  }
  const renderGroup = (group: { key: string; rows: ProjectDocument[] }) => <>
        {group.key === 'legacy' && <Alert type="info" showIcon message="旧资料与原审核信息保留，尚未猜配到新阶段" description="负责人可在下方资料要求中明确分类；未分类资料不冒充已满足新阶段门禁。" style={{ marginBottom: 12 }} />}
        {mobile ? <div className="field-card-list">{group.rows.map(row => <article className="field-record-card" key={row.id}>
          <h3>{row.code} {row.name}</h3>{row.vehicle_label && <p>{row.vehicle_label}</p>}{row.period_key && <Tag>{row.period_key}</Tag>}
            {row.trigger_event && <p className="documents-note">{row.trigger_event.source_type==='issue'?`问题：${row.trigger_event.source_metadata.title || '原问题'}`:`人员离开：${row.trigger_event.source_metadata.member_name || '原成员'}`} · {row.trigger_event.source_metadata.note}</p>}
          <div>{renderState(row)}</div><p>{row.due_is_estimated && '预计截止 '}{deadlineLabel(row.due_at, row.due_basis?.timezone || data?.timezone || 'Asia/Shanghai')}</p>
          <p className="documents-note">{basisLabel(row)}</p><p>负责人：{row.effective_owner_name || '待指派'}{row.owner_warning && <Typography.Text type="warning"> · {row.owner_warning}</Typography.Text>}</p>{renderFile(row)}<div className="field-record-actions">{renderActions(row)}</div>
        </article>)}</div> : <Table<ProjectDocument> rowKey="id" dataSource={group.rows} pagination={{ pageSize: 15 }} size="small" scroll={{ x: 880 }} loading={loading}
          rowSelection={canSubmit || canExport ? { selectedRowKeys: selected, preserveSelectedRowKeys: true, onChange: keys => setSelected(keys.map(String)), getCheckboxProps: row => ({ disabled: (!canExport && row.applicable === false) || busy }) } : undefined}
          columns={[
              { title: '资料', width: 260, render: (_, row) => <><Typography.Text strong>{row.code} {row.name}</Typography.Text><div>{row.vehicle_label}{row.period_key && ` · ${row.period_key}`}</div>{row.trigger_event && <div className="documents-note">{row.trigger_event.source_type==='issue'?`问题：${row.trigger_event.source_metadata.title || '原问题'}`:`人员离开：${row.trigger_event.source_metadata.member_name || '原成员'}`}<div>{row.trigger_event.source_metadata.note}</div></div>}{row.template_no && <Typography.Text type="secondary">{row.template_no}</Typography.Text>}</> },
            { title: '状态', width: 150, render: (_, row) => renderState(row) },
            { title: '截止', width: 150, render: (_, row) => row.due_at ? <>{row.due_is_estimated && <Tag>预计</Tag>}{deadlineLabel(row.due_at, row.due_basis?.timezone || data?.timezone || 'Asia/Shanghai')}<div className="documents-note">{basisLabel(row)}</div></> : <Tooltip title={basisLabel(row)}><Typography.Text type="secondary" className="documents-due-pending">待定</Typography.Text></Tooltip> },
            { title: '负责人', width: 150, render: (_, row) => <>{row.effective_owner_name || '待指派'}{row.owner_warning && <div className="documents-note">{row.owner_warning}</div>}</> },
            { title: '最近文件', width: 200, render: (_, row) => renderFile(row) },
            { title: '操作', width: 310, render: (_, row) => renderActions(row) },
          ]} />}
</>
  const [panel, setPanel] = useState<'requirements' | 'storage' | null>(null)
  const onDefinitionSaved = useCallback(() => { void load() }, [load])
  return <div className="field-work-page project-documents-page">
    <WorkPageHeader title="资料" description="按阶段提交文件，保留每次版本；同一文件可以同时满足多项要求。"
      meta={data ? `${current.length} 项资料 · 待交 ${current.filter(row => row.status === 'pending').length} · 已提交 ${current.filter(row => row.status === 'submitted').length} · 不适用 ${current.filter(row => row.status === 'waived').length}` : loadError ? '资料状态尚未读取' : '正在读取资料状态'}
      primary={canSubmit && <Button type="primary" icon={<UploadOutlined />} disabled={busy || loading} onClick={() => openUpload()}>上传资料或文件</Button>}
      tools={<Dropdown trigger={['click']} menu={{ items: [
        { key: 'refresh', label: '刷新资料', onClick: () => void load() },
        { key: 'acceptance', label: '验收记录', onClick: () => setAcceptanceOpen(true) },
        { key: 'procurement', label: '采购明细', onClick: () => setProcurementOpen(true) },
        { key: 'requirements', label: '资料要求与等待条件', onClick: () => setPanel('requirements') },
        { key: 'storage', label: '项目存储与保留策略', onClick: () => setPanel('storage') },
      ] }}><Button loading={loading}>更多 <DownOutlined /></Button></Dropdown>} />
    {data?.storage_warnings?.map((warning, index) => <Alert key={index} type="warning" showIcon message={warning} />)}
    {loadError && <Alert type="error" showIcon message="资料清单加载失败" description={loadError} action={<Button onClick={() => void load()}>重试</Button>} />}
    {actionError && <Alert type="error" showIcon message={actionError} style={{ marginBottom: 12 }} />}
    {!!data?.unclassified_files?.length && <Alert type="warning" showIcon style={{ marginBottom: 12 }} message={`有 ${data.unclassified_files.length} 个上传文件还没有归到资料要求`}
      action={<Button size="small" onClick={() => document.getElementById('documents-unclassified')?.scrollIntoView({ behavior: 'smooth' })}>去归类</Button>} />}
    {triggerFilter && <Alert type="info" message="正在查看单个事件生成的资料" action={<Button href={`/pm/projects/${projectId}/documents`}>查看全部资料</Button>} style={{marginBottom:12}} />}
    {data?.trigger_events?.filter(event=>event.source_metadata.warning).map(event=><Alert key={event.id} type="warning" showIcon message={`${event.source_metadata.title || event.source_metadata.member_name || '真实事件'}：${event.source_metadata.warning}`} style={{marginBottom:12}} />)}
    {data?.document_actions?.owner_warnings?.length ? <Typography.Text type="warning" className="documents-owner-warning">{data.document_actions.owner_warnings.length} 项资料的负责人需核对，可在资料行指派</Typography.Text> : null}
    <WorkSection className="documents-list" filters={<Space wrap>
      <Input.Search aria-label="搜索项目资料" placeholder="搜索编号、资料、车号或周期" allowClear value={search} onChange={event => setSearch(event.target.value)} style={{ width: 260 }} />
      {vehicleOptions.length > 0 && <Select aria-label="筛选车辆资料" allowClear showSearch optionFilterProp="label" placeholder="全部车辆" value={vehicle} onChange={setVehicle} options={vehicleOptions} style={{ minWidth: 150 }} />}
      <Segmented aria-label="资料状态" value={status} onChange={value => setStatus(String(value))} options={[{ value: 'all', label: '全部' }, { value: 'pending', label: '待提交' }, { value: 'week', label: <span>本周待交{!!data?.document_actions?.this_week_count && <span className="documents-filter-count">{data.document_actions.this_week_count}</span>}</span> }, { value: 'overdue', label: <span>逾期{!!data?.document_actions?.overdue_count && <span className="documents-filter-count is-danger">{data.document_actions.overdue_count}</span>}</span> }, { value: 'submitted', label: '已提交' }, { value: 'waived', label: '不适用' }, { value: 'on_demand', label: '抽查' }]} />
      {data && <InfoHint text={`现场时区 ${data.timezone}；截止时间按资料规则的时区显示，已提交资料保留原截止依据；“预计”截止以计划日期推算。账号密码类信息请放在密码管理工具中，这里只写位置说明；保密资料不会向外部人员展示。`} />}
    </Space>} extra={(canSubmit || canExport) && selected.length > 0 && <Space><Typography.Text>已选 {selected.length} 项</Typography.Text>{canSubmit && selected.every(id => documents.find(row => row.id === id)?.applicable !== false) && <Button disabled={busy || loading} onClick={() => openUpload(selected)}>同一文件提交所选资料</Button>}{canExport && <Button disabled={busy || loading} onClick={async () => { if (mutation.current) return; const ticket = generation.current; mutation.current = true; setBusy(true); setActionError(''); try { await downloadSelectedDocuments(projectId, selected) } catch (failure) { if (ticket === generation.current) setActionError(errMsg(failure)) } finally { if (ticket === generation.current) { mutation.current = false; setBusy(false) } } }}>打包所选资料（最新版本）</Button>}<Button onClick={() => setSelected([])}>取消选择</Button></Space>}>
      {!loading && !loadError && !visible.length && <Empty description={documents.length ? '当前筛选没有资料' : '还没有已生成的资料实例；等待条件和资料要求见下方'} />}
      {stageGroups.length > 0 && <Tabs className="documents-stage-tabs" activeKey={activeStage} onChange={key => { setStage(key); setSelected([]) }} items={[
        ...stageGroups.map(group => { const pending = group.rows.filter(row => row.status === 'pending' && row.applicable !== false).length
          return { key: group.key, label: <span>{stageName(group.key)} <span className="documents-stage-count">{pending ? `${pending} 待交` : '已齐'}</span></span> } }),
        { key: 'all', label: `全部 ${stageFiltered.length}` },
      ]} />}
      {activeStage === 'all'
        ? <Collapse className="documents-stages" bordered={false} defaultActiveKey={['4', '5', '6', '7', '8', '9', 'legacy']} items={grouped.map(group => ({ key: group.key, label: `${stageName(group.key)} · ${group.rows.length} 项`, children: renderGroup(group) }))} />
        : grouped.map(group => <div key={group.key} className="documents-stage-body">{renderGroup(group)}</div>)}
    </WorkSection>
    <Drawer title="资料要求与等待条件" open={panel === 'requirements'} onClose={() => setPanel(null)} width="min(860px, calc(100vw - 16px))">
    <WorkSection description="这里保留项目自己的要求快照。周期、事件触发或尚未建档的车辆满足条件后才生成应交资料。"
      extra={canManage && <Button icon={<PlusOutlined />} disabled={busy || loading} onClick={() => setEditing('new')}>新增资料要求</Button>}>
      <Typography.Paragraph type="secondary">{definitions.length} 项资料要求{waiting.length ? ` · ${waiting.length} 项等待条件` : ''}</Typography.Paragraph><Table<ProjectDocumentDefinition> rowKey="id" dataSource={definitions} size="small" pagination={{ pageSize: 15 }} scroll={{ x: 650 }} columns={[
        { title: '资料要求', render: (_, row) => <><Typography.Text strong>{row.code} {row.name}</Typography.Text><div className="documents-note">{stageName(row.stage_key)} · {row.scope === 'vehicle' ? '每台车' : '项目一份'}</div></> },
        { title: '生成与输出时机', render: (_, row) => <>{documentRuleLabel(row)}{row.waiting_reason && <div><Tag color="blue">{row.waiting_reason}</Tag></div>}{row.source_metadata && <div className="documents-note">原始来源与审核记录保留</div>}</> },
        { title: '操作', render: (_, row) => <Space wrap>{row.blank_file_id && <Button size="small" onClick={() => void download(`/projects/${encodeURIComponent(projectId)}/documents/requirements/${encodeURIComponent(row.id)}/blank-file`, `${row.name}空白模板`)}>下载模板</Button>}{canManageConfidentiality && <Button size="small" disabled={busy} onClick={() => setConfidentialityTarget({ kind: 'definition', row })}>保密范围</Button>}{canManage && <Button size="small" disabled={busy || loading} onClick={() => setEditing(row)}>{row.stage_key === 'legacy' ? '明确分类' : '编辑要求'}</Button>}</Space> },
      ]} />
    </WorkSection>
    </Drawer>
    <Drawer title="项目存储与周资料保留策略" open={panel === 'storage'} onClose={() => setPanel(null)} width="min(760px, calc(100vw - 16px))" destroyOnHidden>
      <ProjectStoragePanel key={projectId} projectId={projectId} canCleanup={deleteCapability && !writeBlocked} onChanged={() => { void load() }} />
    </Drawer>
    <div id="documents-unclassified" />
    {!!data?.unclassified_files?.length && <WorkSection title="未归类文件" description="上传后尚未对应资料要求的文件；问题照片等仍按原所属事项保留。">
      <Table<ProjectFile> rowKey="id" dataSource={data?.unclassified_files ?? []} size="small" loading={loading} pagination={{ pageSize: 10 }} scroll={{ x: 540 }} locale={{ emptyText: <Empty description={loadError ? "文件清单尚未读取" : "暂无未归类文件"} /> }} columns={[
        { title: '文件', render: (_, row) => <><Button type="link" size="small" icon={<DownloadOutlined />} onClick={() => void download(row.download_url, row.filename)}>{row.filename}</Button>{row.confidential && <Tag color="orange">保密</Tag>}<div className="documents-note">{sizeLabel(row.file_size)} · {row.uploaded_by_name || '原上传人未记录'} · {formatDateTime(row.uploaded_at)}</div></> },
        { title: '归属', render: (_, row) => row.entity_type === 'issue' ? '问题附件' : row.entity_type === 'task' ? '工作附件' : row.category || '项目文件' },
        { title: '操作', render: (_, row) => <Space>{canManageConfidentiality && <Button size="small" disabled={busy} onClick={() => setConfidentialityTarget({ kind: 'file', row })}>附件保密范围</Button>}{canSubmit && <Button size="small" disabled={busy || loading} onClick={() => openUpload([], row)}>关联资料</Button>}{canDeleteFile && <Popconfirm title="删除此未引用文件？已被资料或其他记录引用的文件会被保留。" onConfirm={() => act(() => projectDocumentsApi.deleteFile(row.id), '未引用文件已删除')}><Button size="small" danger disabled={busy || loading}>删除</Button></Popconfirm>}</Space> },
      ]} />
    </WorkSection>}
    <Modal title="指派资料负责人" okText="保存负责人" cancelText="取消" open={!!ownerEditing} destroyOnHidden confirmLoading={busy} okButtonProps={{ disabled: !canManage }}
      onCancel={() => !busy && setOwnerEditing(null)} onOk={() => { if (ownerEditing) void act(() => projectDocumentsApi.assignOwner(projectId, ownerEditing.id, ownerId ?? null, ownerEditing.version), '资料负责人已更新').then(ok => ok && setOwnerEditing(null)) }}>
      <Typography.Paragraph>{ownerEditing && rowName(ownerEditing)}</Typography.Paragraph>
      <Select aria-label="资料负责人" allowClear showSearch optionFilterProp="label" style={{ width: '100%' }} value={ownerId} onChange={setOwnerId}
        placeholder="默认技术负责人 / 项目经理" options={(data?.owner_options ?? []).map(person => ({ value: person.id, label: person.name }))} />
      <Typography.Paragraph type="secondary">留空时默认由活跃技术负责人接收提醒，其次为项目经理。负责人失效会显示提示，并转交可联系的负责人或管理员。</Typography.Paragraph>
    </Modal>
    <ProjectDocumentRequirementEditor canSetConfidentiality={canManageConfidentiality} ownerOptions={data?.owner_options} canEdit={canManage} key={projectId} projectId={projectId} editing={editing} onClose={() => setEditing(null)} onSaved={onDefinitionSaved} onDirtyChange={setRequirementDirty} />
    <DocumentConfidentialityModal key={`confidentiality-${projectId}`} projectId={projectId} target={confidentialityTarget} disabled={!canManageConfidentiality || busy}
      onClose={() => { setConfidentialityTarget(null); setConfidentialityDirty(false) }} onDirtyChange={setConfidentialityDirty}
      onSaved={async () => { await load(); onProjectChange?.() }} />
    <Modal key={`${projectId}:${uploadEpoch}`} title={uploadMode === 'existing' ? '用现有文件提交资料' : '上传资料或文件'} open={uploadOpen} onCancel={() => { if (!busy) { setUploadOpen(false); setUploadFile(null); setExistingFileId(undefined); setUploadNote('') } }}
      onOk={() => void submitUpload()} confirmLoading={busy} okText="确认提交" cancelText="取消" maskClosable={false} okButtonProps={{ disabled: !canSubmit || loading || (uploadMode === 'existing' && (filesLoading || !!filesError || !existingFileId || !uploadIds.length)) || (uploadMode === 'upload' && (!uploadFile || (uploadConfidential && (!canManageConfidentiality || uploadPeopleLoading || !!uploadPeopleError)))) }}>
      {(uploadError || actionError) && <Alert type="error" showIcon message={uploadError || actionError} />}
      <Typography.Paragraph>选择要同时满足的资料。新文件不选资料时先保存在未归类文件；不能空提交。</Typography.Paragraph>
      <Space direction="vertical" size={14} style={{ width: '100%' }}>
        <Select aria-label="同时满足的资料" mode="multiple" showSearch optionFilterProp="label" value={uploadIds} onChange={setUploadIds} disabled={busy} style={{ width: '100%' }} placeholder="选择一个或多个资料要求" options={documents.filter(row => row.applicable !== false).map(row => ({ value: row.id, label: rowName(row) }))} />
        <Segmented aria-label="文件来源" value={uploadMode} disabled={busy} onChange={value => { setUploadMode(value as 'upload' | 'existing'); setUploadError(''); if (value === 'existing') void getFiles() }} options={[{ value: 'upload', label: '上传新文件' }, { value: 'existing', label: '选择本项目文件' }]} />
        {uploadMode === 'upload' && canManageConfidentiality && <>
          <Typography.Text type="secondary">关联保密资料后自动沿用资料范围；附件可额外限制，在首次上传提交时一并生效。</Typography.Text>
          <Space><Typography.Text>附件额外保密</Typography.Text><Switch aria-label="上传附件额外保密" checked={uploadConfidential} disabled={busy} onChange={setUploadConfidential} /></Space>
          {uploadConfidential && <Select aria-label="上传附件指定可见人员" mode="multiple" optionFilterProp="label" value={uploadPeople} onChange={setUploadPeople}
            disabled={busy || uploadPeopleLoading || !!uploadPeopleError} loading={uploadPeopleLoading} placeholder="默认仅项目负责人可见" style={{ width: '100%' }}
            options={uploadMembers.map(member => ({ value: member.id, label: member.display_name }))} />}
        </>}
        {uploadMode === 'upload' && uploadConfidential && uploadPeopleError && <Alert type="error" message={uploadPeopleError} />}
        {uploadMode === 'upload' ? <><Input type="file" aria-label="选择资料文件" disabled={busy} onChange={event => {
          const file = event.target.files?.[0] ?? null
          setUploadFile(file); setUploadError('')
        }} /><Typography.Text type="secondary">支持分片续传，默认每个文件不超过 2 GB；服务器会核对当前上限。</Typography.Text></> : <>
          {filesError && <Alert type="error" message={filesError} action={<Button onClick={() => void getFiles()}>重试文件列表</Button>} />}
          <Select aria-label="本项目已有文件" showSearch optionFilterProp="label" value={existingFileId} onChange={setExistingFileId} loading={filesLoading} disabled={busy || !!filesError} style={{ width: '100%' }} placeholder="选择已上传的文件" options={existingFiles.map(file => ({ value: file.id, label: file.filename }))} />
        </>}
        {signatureKeys.length > 0 && <fieldset disabled={busy}><legend>签单实际发生日期（可选）</legend><p>按签单上真实日期登记关键事件；未填写时仅保存文件，可稍后由负责人补登。上传时间不会作为实际发生时间，项目状态仍需人工确认。</p>{signatureKeys.map(key => <label key={key} style={{ display: 'block', marginBottom: 8 }}>{PROJECT_EVENT_LABELS[key]}<Input type="date" aria-label={`${PROJECT_EVENT_LABELS[key]}签单实际日期`} value={signatureDates[key] || ''} onChange={event => setSignatureDates(previous => ({ ...previous, [key]: event.target.value }))} /></label>)}</fieldset>}
        <Input.TextArea aria-label="本次提交说明" placeholder="本次版本说明（可选）" value={uploadNote} onChange={event => setUploadNote(event.target.value)} disabled={busy} rows={3} maxLength={2000} />
      </Space>
    </Modal>
    <Modal title={statusChange?.status === 'waived' ? '标为不适用' : statusChange?.row.status === 'submitted' ? '撤回提交' : '恢复待提交'} open={statusChange !== null} onCancel={() => !busy && setStatusChange(null)} okText="保存理由" cancelText="取消" confirmLoading={busy} okButtonProps={{ disabled: !reason.trim() || !canSubmit }} onOk={async () => {
      if (!statusChange || !reason.trim()) return
      if (await act(() => projectDocumentsApi.setStatus(projectId, statusChange.row, statusChange.status, reason.trim()), '资料状态与理由已记录')) setStatusChange(null)
    }}>
      {actionError && <Alert type="error" message={actionError} />}<p>{statusChange?.row.name}</p><Input.TextArea aria-label="资料状态修改理由" value={reason} onChange={event => setReason(event.target.value)} placeholder="请说明理由，已有历史版本会保留" rows={3} maxLength={1000} disabled={busy} />
    </Modal>
    <Drawer title={history ? `${history.code} ${history.name} · 版本记录` : '版本记录'} open={historyId !== null} onClose={() => !busy && setHistoryId(null)} width={mobile ? '100%' : 580} destroyOnHidden>
      {history ? <>
        <div>{renderState(history)}</div>{history.note && <Typography.Paragraph>{history.note}</Typography.Paragraph>}
        {history.source_metadata && <Alert type="info" showIcon message="原始资料与审核事实已保留" description="没有真实附件的旧完成记录仍需补充文件，才能成为已提交资料。" />}
        {!history.versions.length && <Empty description="尚无提交版本" />}
        {history.versions.slice().reverse().map((version: ProjectDocumentVersion, index) => <article className="field-record-card" key={version.id}>
          <Space wrap><Typography.Text strong>{version.filename}</Typography.Text>{version.id === history.latest_version?.id && <Tag color="blue">最近版本</Tag>}<Tag>第 {history.versions.length - index} 版</Tag></Space>
          <p>{version.uploaded_by_name || '原提交人未记录'} · {formatDateTime(version.uploaded_at)} · {sizeLabel(version.file_size)}</p>
          {version.storage_state === 'removed_by_policy' && <Alert type="info" message="文件已按保留策略清理，版本记录仍保留" description={version.removal ? `${version.removal.removed_by_name} · ${formatDateTime(version.removal.removed_at)} · ${version.removal.reason}` : undefined} />}
          {version.note && <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>{version.note}</Typography.Paragraph>}
          {!!version.review_metadata?.generated && <Typography.Paragraph type="secondary">系统生成 · 原记录与日期保留</Typography.Paragraph>}
          {version.review_metadata && Object.keys(version.review_metadata).some(key => key !== 'generated') && <ReviewTrail metadata={version.review_metadata} />}
          <Space wrap><Button icon={<DownloadOutlined />} disabled={!version.download_url || version.storage_state === 'removed_by_policy'} onClick={() => void download(version.download_url, version.filename)}>下载此版本</Button>
            {canManageConfidentiality && version.file && <Button disabled={busy} onClick={() => setConfidentialityTarget({ kind: 'file', row: version.file! })}>附件保密范围</Button>}
            {canManage && !!version.download_url && version.uploaded_by !== user?.id && <><Button disabled={busy} onClick={() => { setReview({ documentId: history.id, versionId: version.id, decision: 'approved' }); setReviewNote('') }}>审核通过</Button><Button disabled={busy} onClick={() => { setReview({ documentId: history.id, versionId: version.id, decision: 'rejected' }); setReviewNote('') }}>退回说明</Button></>}
          </Space>
        </article>)}
      </> : <Empty description="此资料已不可见，请刷新资料清单" />}
    </Drawer>
    <Modal title={review?.decision === 'approved' ? '记录可选审核' : '记录退回说明'} open={review !== null} okText="保存审核记录" cancelText="取消" onCancel={() => !busy && setReview(null)} confirmLoading={busy} okButtonProps={{ disabled: !canManage || (review?.decision === 'rejected' && !reviewNote.trim()) }} onOk={async () => {
      if (!review) return
      if (await act(() => projectDocumentsApi.review(projectId, review.documentId, review.versionId, review.decision, reviewNote.trim()), '审核信息已保存，资料提交状态保持')) setReview(null)
    }}><Typography.Paragraph>审核为可选记录，不改变资料已提交事实或门禁口径。</Typography.Paragraph>{actionError && <Alert type="error" message={actionError} />}<Input.TextArea aria-label="审核说明" value={reviewNote} onChange={event => setReviewNote(event.target.value)} placeholder={review?.decision === 'rejected' ? '退回必须填写说明' : '审核说明（可选）'} rows={3} maxLength={2000} /></Modal>
    <Drawer title="4.4 · 采购明细" open={procurementOpen} onClose={() => closePanel(procurementDirty, () => setProcurementOpen(false), () => setProcurementDirty(false))} width={mobile ? '100%' : 960} destroyOnHidden>
      {procurementOpen && <ProcurementPanel key={projectId} projectId={projectId} templateId={templateId} onDirtyChange={setProcurementDirty} />}
    </Drawer>
    <Drawer title="发车前资料确认" open={entryOpen} onClose={() => closePanel(entryDirty, () => setEntryOpen(false), () => setEntryDirty(false))} width={mobile ? '100%' : 720} destroyOnHidden>{entryOpen && <EntryReviewPanel key={projectId} projectId={projectId} onConfirmed={() => { void load(); onProjectChange?.() }} onDirtyChange={setEntryDirty} />}</Drawer>
    <Drawer title="7.1 · 验收记录" open={acceptanceOpen} onClose={() => closePanel(acceptanceDirty, () => setAcceptanceOpen(false), () => setAcceptanceDirty(false))} width={mobile ? '100%' : 760} destroyOnHidden>
      {acceptanceOpen && <AcceptanceRecordsPanel key={projectId} projectId={projectId} refreshToken={data?.version} onChanged={() => { void load(); onProjectChange?.() }} onDirtyChange={setAcceptanceDirty} onUpload={canSubmit ? () => openUpload(documents.filter(row => row.code === '7.1' && row.applicable !== false).map(row => row.id)) : undefined} />}
    </Drawer>
  </div>
}
