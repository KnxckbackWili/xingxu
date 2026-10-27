import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Dropdown, Modal, Select, Space, Switch, Typography } from 'antd'
import { projectDocumentsApi, type GeneratedContactSource, type GeneratedFormKind, type GeneratedFormOptions } from '../../../api/projectDocuments'
import { errMsg } from '../../../api/client'

const names = { lifecycle: '由系统生成本周生命周期表', contact: '由内部联系单生成', inventory: '由物品流水生成' }

export default function GeneratedFormControl({ projectId, documentId, kind, busy, canManageConfidentiality, onGenerate, generationError }: {
  projectId: string; documentId: string; kind: GeneratedFormKind; busy: boolean; canManageConfidentiality: boolean
  generationError?: string
  onGenerate: (options: GeneratedFormOptions) => Promise<boolean>
}) {
  const [open, setOpen] = useState(false)
  const [privateOutput, setPrivateOutput] = useState(false)
  const [people, setPeople] = useState<string[]>([])
  const [members, setMembers] = useState<{ id: string; display_name: string }[]>([])
  const [sources, setSources] = useState<GeneratedContactSource[]>([])
  const [applicationId, setApplicationId] = useState<string>()
  const [sourceLoading, setSourceLoading] = useState(false)
  const [peopleLoading, setPeopleLoading] = useState(false)
  const [error, setError] = useState('')
  const [peopleError, setPeopleError] = useState('')
  const [failed, setFailed] = useState(false)
  const [retry, setRetry] = useState(0)
  const ticket = useRef(0)
  const lock = useRef(false)
  useEffect(() => { setOpen(false); setPeople([]); setMembers([]); setSources([]); setApplicationId(undefined); setPrivateOutput(false); setError(''); lock.current = false; return () => { ticket.current++ } }, [projectId, documentId])
  useEffect(() => {
    if (!open || !privateOutput || !canManageConfidentiality) return
    let current = true; setPeopleLoading(true); setPeopleError('')
    projectDocumentsApi.confidentialityMembers(projectId).then(rows => {
      if (!Array.isArray(rows)) throw new Error('保密人员无法读取')
      if (current) setMembers(rows)
    }).catch(failure => { if (current) setPeopleError(errMsg(failure)) }).finally(() => { if (current) setPeopleLoading(false) })
    return () => { current = false }
  }, [open, privateOutput, canManageConfidentiality, projectId, retry])
  const peopleKey = JSON.stringify(people)
  useEffect(() => {
    const current = ++ticket.current
    if (!open || kind !== 'contact') return
    setSourceLoading(true); setError(''); setApplicationId(undefined); setSources([])
    projectDocumentsApi.generationSources(projectId, documentId, { confidential: privateOutput, confidentialUserIds: people }).then(rows => {
      if (!Array.isArray(rows)) throw new Error('联系单来源无法读取')
      if (current === ticket.current) setSources(rows)
    }).catch(failure => { if (current === ticket.current) setError(errMsg(failure)) }).finally(() => { if (current === ticket.current) setSourceLoading(false) })
    return () => { ticket.current++ }
  }, [open, kind, projectId, documentId, privateOutput, peopleKey, retry])
  const disabled = busy || sourceLoading || (privateOutput && (!canManageConfidentiality || peopleLoading || !!peopleError)) || !!error || (kind === 'contact' && !sources.some(row => row.id === applicationId))
  const settings = (privateFile = false) => { setPrivateOutput(privateFile); setPeople([]); setApplicationId(undefined); setError(''); setPeopleError(''); setFailed(false); setOpen(true) }
  const submit = async () => {
    if (disabled || lock.current) return
    const current = ticket.current; lock.current = true
    try {
      if (await onGenerate({ confidential: privateOutput, confidentialUserIds: privateOutput ? people : [], ...(kind === 'contact' ? { applicationId } : {}) })) {
        if (current === ticket.current) setOpen(false)
      } else if (current === ticket.current) setFailed(true)
    } finally { lock.current = false }
  }
  const direct = () => kind === 'contact' ? settings() : void onGenerate({})
  return <>
    {canManageConfidentiality ? <Dropdown.Button size="small" disabled={busy} onClick={direct}
      menu={{ items: [{ key: 'private', label: '保密输出设置', onClick: () => settings(true) }] }}>{names[kind]}</Dropdown.Button>
      : <Button size="small" disabled={busy} onClick={direct}>{names[kind]}</Button>}
    <Modal title={names[kind]} open={open} onCancel={() => !busy && setOpen(false)} onOk={() => void submit()}
      okText="生成并提交当前版本" cancelText="取消" confirmLoading={busy} okButtonProps={{ disabled }} maskClosable={false}>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Typography.Paragraph>使用现有真实记录生成文件，保存为本资料的新版本；原记录和日期保持。</Typography.Paragraph>
        <Alert type="info" showIcon message="默认排除保密或无法核实权限的来源。保密输出也只包含全部指定读者都有权查看的来源，不展示被排除的名称或数量。" />
        {canManageConfidentiality && <Space><Switch aria-label="生成保密附件" checked={privateOutput} disabled={busy} onChange={value => { setPrivateOutput(value); setPeople([]) }} /><span>生成保密附件</span></Space>}
        {privateOutput && <><Typography.Text type="secondary">当前项目负责人始终可见，其他人员与资料家族范围取交集。</Typography.Text>
          <Select mode="multiple" aria-label="生成附件指定人员" placeholder="不指定时仅项目负责人" value={people} onChange={setPeople} loading={peopleLoading} disabled={busy || !canManageConfidentiality || peopleLoading || !!peopleError}
            style={{ width: '100%' }} options={members.map(row => ({ value: row.id, label: row.display_name }))} />
          {!canManageConfidentiality && <Alert type="error" message="保密设置权限已变化，请取消后重新核对" />}</>}
        {kind === 'contact' && <Select aria-label="选择原物品申请" placeholder="选择已有物品申请或内部联系单" loading={sourceLoading} value={applicationId} onChange={setApplicationId} disabled={busy || sourceLoading || !!error}
          style={{ width: '100%' }} options={sources.map(row => ({ value: row.id, label: `${row.title || row.item_name || '未填写事项'}${row.apply_date ? ` · ${row.apply_date}` : ''}` }))} />}
        {kind === 'contact' && !sourceLoading && !error && !sources.length && <Alert type="info" message="当前输出范围没有可用的申请记录。可到物品页维护申请后再生成。" />}
        {(error || peopleError) && <Alert type="error" message={error || peopleError} action={<Button disabled={busy} onClick={() => setRetry(value => value + 1)}>重新读取</Button>} />}
        {failed && <Alert type="error" message={generationError || '文件未生成，请核对当前权限与来源后重试'} />}
      </Space>
    </Modal>
  </>
}
