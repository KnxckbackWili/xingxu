import { useEffect, useRef, useState } from 'react'
import { Alert, Modal, Select, Space, Switch, Typography } from 'antd'
import { projectDocumentsApi, type ProjectDocument, type ProjectDocumentDefinition, type ProjectFile } from '../../../api/projectDocuments'
import { errMsg } from '../../../api/client'

export type ConfidentialityTarget =
  | { kind: 'document'; row: ProjectDocument }
  | { kind: 'definition'; row: ProjectDocumentDefinition }
  | { kind: 'file'; row: ProjectFile }

export default function DocumentConfidentialityModal({ projectId, target, disabled, onClose, onSaved, onDirtyChange }: {
  projectId: string; target: ConfidentialityTarget | null; disabled: boolean
  onClose: () => void; onSaved: () => Promise<void>; onDirtyChange: (dirty: boolean) => void
}) {
  const [confidential, setConfidential] = useState(false)
  const [people, setPeople] = useState<string[]>([])
  const [members, setMembers] = useState<{ id: string; display_name: string }[]>([])
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const ticket = useRef(0)
  const mutation = useRef(false)
  const dirty = useRef(false)
  useEffect(() => {
    const current = ++ticket.current
    mutation.current = false; dirty.current = false; setBusy(false); setError(''); onDirtyChange(false)
    setConfidential(target?.kind === 'definition' ? target.row.confidential_default : target?.kind === 'file' ? !!target.row.confidential_explicit : !!target?.row.confidential)
    setPeople(target?.row.confidential_user_ids ?? []); setMembers([])
    if (target) {
      setLoading(true)
      projectDocumentsApi.confidentialityMembers(projectId).then(rows => {
        if (!Array.isArray(rows) || rows.some(row => typeof row.id !== 'string' || typeof row.display_name !== 'string')) throw new Error('保密人员列表无法读取')
        if (current === ticket.current) setMembers(rows)
      }).catch(failure => { if (current === ticket.current) setError(errMsg(failure)) })
        .finally(() => { if (current === ticket.current) setLoading(false) })
    } else setLoading(false)
    return () => { ticket.current++ }
  }, [projectId, target, onDirtyChange])
  const changed = () => { dirty.current = true; onDirtyChange(true) }
  const close = () => {
    if (busy) return
    if (dirty.current) Modal.confirm({ title: '保密范围尚未保存', content: '放弃本次修改？', okText: '放弃修改', cancelText: '继续编辑', onOk: onClose })
    else onClose()
  }
  const save = async () => {
    if (!target || disabled || loading || error || mutation.current) return
    const current = ticket.current
    mutation.current = true; setBusy(true)
    try {
      await projectDocumentsApi.setConfidentiality(projectId, target.kind, target.row.id, {
        confidential, confidential_user_ids: confidential ? people : [],
        version: target.kind === 'document' ? target.row.version : target.row.access_version ?? 1,
      })
      if (current !== ticket.current) return
      dirty.current = false; onDirtyChange(false); await onSaved(); onClose()
    } catch (failure) { if (current === ticket.current) setError(errMsg(failure)) }
    finally { if (current === ticket.current) { mutation.current = false; setBusy(false) } }
  }
  return <Modal title={target?.kind === 'file' ? '附件保密范围' : '资料要求保密范围'} open={target !== null}
    onCancel={close} onOk={() => void save()} okText="保存保密范围" cancelText="取消" confirmLoading={busy}
    maskClosable={false} okButtonProps={{ disabled: disabled || loading || !!error }}>
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Typography.Text strong>{target && ('filename' in target.row ? target.row.filename : `${target.row.code} ${target.row.name}`)}</Typography.Text>
      <Alert type="warning" showIcon message={target?.kind === 'file'
        ? '附件自身的限制与所有关联保密资料取交集；关闭这里的限制也不会解除关联资料的保密范围。'
        : '此设置作用于此资料要求的全部期次、历史版本和以后生成项。'} />
      <Typography.Paragraph>项目负责人默认可见，随当前负责人变更。系统管理员、技术负责人、上传人和提交人都需要明确指定；外部人员永远不可见保密内容。</Typography.Paragraph>
      {error && <Alert type="error" showIcon message={error} description="尚未保存。若版本或权限已变化，请取消后刷新资料，再重新设置。" />}
      <Space><Typography.Text>保密</Typography.Text><Switch aria-label="保密" checked={confidential} disabled={busy || disabled || loading || !!error} onChange={value => { setConfidential(value); changed() }} /></Space>
      <Select aria-label="指定可见人员" mode="multiple" style={{ width: '100%' }} placeholder="仅项目负责人可见（可指定其他内部人员）"
        optionFilterProp="label" value={people} loading={loading} disabled={!confidential || busy || disabled || loading || !!error}
        options={[...members.map(member => ({ value: member.id, label: member.display_name })),
          ...people.filter(id => !loading && !members.some(member => member.id === id)).map(id => ({ value: id, label: '原指定人员（已不可用，请移除）' }))]} onChange={value => { setPeople(value); changed() }} />
    </Space>
  </Modal>
}
