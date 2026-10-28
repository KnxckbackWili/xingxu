import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Descriptions, Modal, Space, Typography, message } from 'antd'
import { DownloadOutlined, UploadOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api, errMsg } from '../api/client'
import { useAuth } from '../stores/auth'
import { hasSystemPermission } from '../constants/systemPermissions'
import { projectStatusMeta } from '../constants/status'
import { draftProjectImport, projectImportSourceStatus } from '../utils/projectImport'
import { useSubmitLock } from '../hooks/useSubmitLock'

/** Import is owned by the advanced export section; account/project changes discard its preview. */
export default function ProjectJsonImport({ projectId }: { projectId: string }) {
  const { user } = useAuth()
  const scope = JSON.stringify([projectId,user?.id,user?.role,user?.permission_version,user?.permission_overrides,user?.system_permissions])
  return <ImportForm key={scope} allowed={hasSystemPermission(user, 'system.import.create')} />
}
function ImportForm({ allowed: canImport }: { allowed: boolean }) {
  const navigate = useNavigate()
  const importInputRef = useRef<HTMLInputElement>(null)
  const importLock = useSubmitLock()
  const importSequence = useRef(0)
  const validationRequest = useRef<number | null>(null)
  const importCreating = useRef(false)
  const [validatingImport, setValidatingImport] = useState(false)
  const [importSourceStatus, setImportSourceStatus] = useState<string | undefined>()
  const [draftPreviewError, setDraftPreviewError] = useState<string | null>(null)
  useEffect(() => () => { importSequence.current++ }, [])
  const [importOpen, setImportOpen] = useState(false)
  const [importPayload, setImportPayload] = useState<any>(null)
  const [importPreview, setImportPreview] = useState<any>(null)
  const [importing, setImporting] = useState(false)
  const downloadImportTemplate = async () => {
    try {
      const response = await api.get('/projects/import/template', { responseType: 'blob', timeout: 600000 })
      const url = URL.createObjectURL(response.data); const link = document.createElement('a'); link.href = url; link.download = '项目导入模板.json'; link.click(); URL.revokeObjectURL(url)
    } catch (error) { message.error(errMsg(error)) }
  }

  const previewImport = async (file: File) => {
    if (!canImport || importCreating.current) return false
    const request = ++importSequence.current
    validationRequest.current = request
    setValidatingImport(true)
    try {
      const payload = JSON.parse(await file.text())
      if (request !== importSequence.current) return false
      const response = await api.post('/projects/import/preview', payload)
      if (request === importSequence.current) {
        setImportPayload(payload); setImportPreview(response.data); setImportOpen(true)
        setImportSourceStatus(undefined); setDraftPreviewError(null)
      }
    } catch (error) {
      if (request === importSequence.current) message.error(error instanceof SyntaxError ? '文件不是有效的 JSON，请检查备份格式；原预检内容已保留' : errMsg(error) || '文件解析失败，原预检内容已保留')
    } finally {
      if (request === importSequence.current) { validationRequest.current = null; setValidatingImport(false) }
    }
    return false
  }

  const previewAsDraft = async () => {
    if (!canImport || importCreating.current || validationRequest.current !== null) return
    const draft = draftProjectImport(importPayload)
    if (!draft) return
    const request = ++importSequence.current
    validationRequest.current = request
    setValidatingImport(true); setDraftPreviewError(null)
    try {
      const { data } = await api.post('/projects/import/preview', draft.payload)
      if (request !== importSequence.current) return
      if (!data.valid) {
        setDraftPreviewError(data.errors?.join('；') || '后端检查未通过')
        return
      }
      setImportPayload(draft.payload); setImportPreview(data); setImportSourceStatus(draft.sourceStatus)
    } catch (error) {
      if (request === importSequence.current) setDraftPreviewError(errMsg(error) || '请稍后重试')
    } finally {
      if (request === importSequence.current) { validationRequest.current = null; setValidatingImport(false) }
    }
  }

  const cancelImport = () => {
    if (importCreating.current) return
    importSequence.current++
    validationRequest.current = null
    setValidatingImport(false); setImportOpen(false)
  }

  const confirmImport = async () => {
    if (!canImport || validationRequest.current !== null || !importPayload || !importPreview?.valid || !importLock.tryAcquire()) return
    const request = importSequence.current
    importCreating.current = true
    setImporting(true)
    try {
      const response = await api.post('/projects/import/json', importPayload)
      if (request !== importSequence.current) return
      message.success(response.data.message)
      setImportOpen(false); setImportPayload(null); setImportPreview(null)
      navigate(`/pm/projects/${response.data.id}`)
    } catch (error) {
      if (request === importSequence.current) message.error('导入失败，预检内容已保留，可重试：' + errMsg(error))
    } finally {
      importLock.release(); importCreating.current = false
      if (request === importSequence.current) setImporting(false)
    }
  }

  if (!canImport) return null
  return <>
    <Space wrap>
      <Button icon={<DownloadOutlined />} onClick={() => void downloadImportTemplate()}>下载导入模板</Button>
      <Button icon={<UploadOutlined />} loading={importing || validatingImport} disabled={importing || validatingImport} onClick={() => importInputRef.current?.click()}>导入 JSON 新建项目</Button>
      <Typography.Text type="secondary">先预检再确认；新项目的交付证据与审核状态需重新提交。</Typography.Text>
      <input ref={importInputRef} type="file" accept=".json,application/json" disabled={importing || validatingImport} hidden onChange={event => { const file=event.target.files?.[0]; if(file) void previewImport(file); event.target.value='' }} />
    </Space>
    {validatingImport && !importOpen && <p role="status">正在预检导入文件…</p>}
      <Modal title="JSON 导入预检" open={importOpen} onCancel={cancelImport} onOk={confirmImport}
        okText="确认创建项目" cancelText="取消" okButtonProps={{ disabled: !importPreview?.valid || validatingImport }} confirmLoading={importing}
        cancelButtonProps={{ disabled: importing }} closable={!importing} maskClosable={!importing} width={720}>
        {importPreview && <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Alert type={importPreview.valid ? 'success' : 'error'} showIcon message={importPreview.valid ? '模板检查通过，可以创建项目' : '模板存在错误，暂不能导入'} />
          <Typography.Text>源项目状态：{projectImportSourceStatus(importPayload) === undefined && importSourceStatus === undefined
            ? '未注明' : projectStatusMeta(importSourceStatus ?? projectImportSourceStatus(importPayload)!).label}</Typography.Text>
          {importSourceStatus !== undefined && <Alert type="info" showIcon message="新项目将从准备开始" description="实施阶段需重新确认；交付附件与审核结果需重新提交。原项目和备份文件保持原样。" />}
          {draftProjectImport(importPayload) && <Space direction="vertical">
            <Typography.Text>复用此项目方案时，可按准备重新预检，再确认创建新项目。</Typography.Text>
            <Button loading={validatingImport} disabled={importing} onClick={previewAsDraft}>按准备重新预检</Button>
          </Space>}
          {draftPreviewError && <Alert type="error" showIcon message="准备预检未通过，原预检内容已保留" description={draftPreviewError} />}
          {!!importPreview.errors?.length && <Alert type="error" showIcon message="必须修正" description={importPreview.errors.join('；')} />}
          {!!importPreview.warnings?.length && <Alert type="warning" showIcon message="导入提醒" description={importPreview.warnings.join('；')} />}
          <Descriptions size="small" bordered column={3} items={[
            { key: 'project', label: '项目', children: importPreview.summary?.project || '-' },
            { key: 'contacts', label: '甲方联系人', children: `${importPreview.summary?.contacts ?? 0} 人` },
            { key: 'vehicle_types', label: '车型', children: `${importPreview.summary?.vehicle_types ?? 0} 种` },
            { key: 'vehicle_units', label: '现场车辆', children: `${importPreview.summary?.vehicle_units ?? 0} 台` },
            { key: 'vehicle_issues', label: '车辆问题', children: `${importPreview.summary?.vehicle_issues ?? 0} 条` },
            { key: 'tasks', label: '任务', children: `${importPreview.summary?.tasks ?? 0} 项` },
            { key: 'document_definitions', label: '资料要求快照', children: `${importPreview.summary?.document_definitions ?? 0} 项` },
            { key: 'project_documents', label: '来源资料实例（需重新提交）', children: `${importPreview.summary?.project_documents ?? 0} 项` },
            { key: 'legacy_document_requirements', label: '历史待分类资料', children: `${importPreview.summary?.legacy_document_requirements ?? 0} 项` },
            { key: 'procurements', label: '采购明细', children: `${importPreview.summary?.procurements ?? 0} 项` },
            { key: 'schedule', label: '排程', children: `${importPreview.summary?.schedule ?? 0} 条` },
            { key: 'issues', label: '项目问题', children: `${importPreview.summary?.issues ?? 0} 条` },
          ]} />
          <Typography.Text type="secondary">附件文件和用户账号不会从 JSON 导入；项目创建后可继续上传文件和分配人员。</Typography.Text>
        </Space>}
      </Modal>

  </>
}
