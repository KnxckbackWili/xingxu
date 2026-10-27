import { useProjectCapability } from '../../../hooks/useProjectCapability'
import HandoverSummary from '../../../components/HandoverSummary'
import { useEffect, useState } from 'react'
import { Button, Drawer, Empty, Form, Input, Modal, Popconfirm, Row, Col, Select, Tag, Typography, message } from 'antd'
import { DeleteOutlined, EditOutlined, PlusOutlined, StarFilled } from '@ant-design/icons'
import { projectApi, type Project } from '../../../api'
import { useSubmitLock } from '../../../hooks/useSubmitLock'
import { errMsg } from '../../../api/client'
import { useAuth } from '../../../stores/auth'
import { WorkPageHeader, WorkSection } from '../../../components/WorkPage'
import { useMediaQuery } from '../../../hooks/useMediaQuery'
import './FieldWorkPages.css'

export default function SiteHandoverPage({ project, onReload }: { project: Project; onReload: () => void }) {
  const { user } = useAuth()
  const canEdit = useProjectCapability('project.update', user?.role === 'admin' || (user?.role === 'pm' && project.manager === user.id) || !!project.is_co_manager)
  const [contacts, setContacts] = useState<any[]>(project.client_contacts ?? [])
  const [contactOpen, setContactOpen] = useState(false)
  const [contactSaving, setContactSaving] = useState(false)
  const contactLock = useSubmitLock()
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [contactForm] = Form.useForm()
  const [entryForm] = Form.useForm()
  const isMobile = useMediaQuery('(max-width: 767px)')
  const [entryOpen, setEntryOpen] = useState(false)
  const [entrySaving, setEntrySaving] = useState(false)
  const [entryError, setEntryError] = useState('')
  const entryLock = useSubmitLock()

  useEffect(() => {
    setContacts(project.client_contacts ?? [])
    if (!entryOpen) entryForm.setFieldsValue(project.entry_plan ?? {})
  }, [project])

  const saveContacts = async (next: any[]) => {
    if (!canEdit || !contactLock.tryAcquire()) return false
    setContactSaving(true)
    try {
      await projectApi.update(project.id, { client_contacts: next })
      setContacts(next); await onReload()
      message.success('甲方联系人已保存')
      return true
    } catch (error) { message.error(errMsg(error)); return false }
    finally { setContactSaving(false); contactLock.release() }
  }

  const submitContact = async (values: any) => {
    const next = contacts.map((item) => ({ ...item, is_primary: values.is_primary ? false : item.is_primary }))
    if (editingIndex == null) next.push(values); else next[editingIndex] = values
    if (await saveContacts(next)) {
      setContactOpen(false); setEditingIndex(null); contactForm.resetFields()
    }
  }

  const saveEntry = async (values: any) => {
    if (!canEdit || !entryLock.tryAcquire()) return
    setEntrySaving(true); setEntryError('')
    try {
      await projectApi.update(project.id, { entry_plan: values })
      setEntryOpen(false); message.success('入场信息已保存'); await onReload()
    } catch (error) { setEntryError(errMsg(error)) }
    finally { entryLock.release(); setEntrySaving(false) }
  }
  const entryFields = [
    ['access_requirements', '入厂手续'], ['tools_ppe', '工具与劳保'], ['safety_requirements', '安全要求'],
    ['vehicle_access', '车辆通行'], ['network_access', '网络接入'], ['notes', '补充说明'],
  ]
  const openEntry = () => { entryForm.setFieldsValue(project.entry_plan ?? {}); setEntryError(''); setEntryOpen(true) }

  return <div className="field-work-page">
    <WorkPageHeader title="联系人与入场" description="到场前先确认联系人、入厂手续和现场要求。"
      primary={canEdit && <Button type="primary" aria-label="编辑入场信息" icon={<EditOutlined />} onClick={openEntry}>编辑入场信息</Button>}
      meta={`${contacts.length} 位联系人`} />
    <WorkSection title="联系人" description="主联系人负责日常协调，其他联系人保留各自负责的事项。"
      extra={canEdit && <Button icon={<PlusOutlined />} onClick={() => { setEditingIndex(null); contactForm.resetFields(); setContactOpen(true) }}>添加联系人</Button>}>
      <div className="field-contact-grid">{contacts.map((item,index) => <article key={index} className="field-record-card">
        <h3>{item.name} {item.is_primary && <Tag color="gold"><StarFilled /> 主联系人</Tag>}</h3>
        <div className="field-record-meta">{[item.department,item.team,item.title].filter(Boolean).join(' · ') || '未填写部门或职务'}</div>
        {item.phone && <p><a className="field-text-link" href={`tel:${String(item.phone).replace(/[^+0-9,;*#]/g,'')}`}>{item.phone}</a></p>}
        {item.email && <p className="field-wrap">{item.email}</p>}
        <dl className="field-contact-facts"><dt>负责事项</dt><dd>{item.responsibility || '未填写'}</dd>{item.decision_scope && <><dt>决策与签字</dt><dd>{item.decision_scope}</dd></>}{item.notes && <><dt>备注</dt><dd>{item.notes}</dd></>}</dl>
        {canEdit && <div className="field-record-actions"><Button disabled={contactSaving} aria-label={`编辑联系人${item.name}`} onClick={() => {setEditingIndex(index);contactForm.setFieldsValue(item);setContactOpen(true)}}>编辑联系人</Button><Popconfirm title="删除这位甲方联系人？" okText="删除" cancelText="取消" onConfirm={() => saveContacts(contacts.filter((_,i)=>i!==index))}><Button disabled={contactSaving} danger aria-label={`删除联系人${item.name}`} icon={<DeleteOutlined />}>删除</Button></Popconfirm></div>}
      </article>)}</div>
      {!contacts.length && <Empty description="还没有联系人，可先登记负责现场协调的人。" />}
    </WorkSection>
    <WorkSection title="入场要求">
      <dl className="field-facts">{entryFields.map(([key,label]) => <div key={key}><dt>{label}</dt><dd>{project.entry_plan?.[key] || '未填写'}</dd></div>)}</dl>
    </WorkSection>
    <details className="field-details"><summary>项目交接记录</summary><HandoverSummary projectId={project.id} /></details>
    <Drawer className="field-work-modal" title="编辑入场信息" width={isMobile ? '100%' : 580} open={entryOpen} onClose={() => {if(!entrySaving)setEntryOpen(false)}}
      extra={<Button type="primary" loading={entrySaving} onClick={() => entryForm.submit()}>保存入场信息</Button>}>
      <Form form={entryForm} layout="vertical" onFinish={saveEntry} disabled={!canEdit || entrySaving}>
        <Form.Item name="access_requirements" label="入厂所需手续"><Input.TextArea rows={2} placeholder="身份证、保险、安全培训、施工证、电脑报备、门禁卡等" /></Form.Item>
        <Form.Item name="tools_ppe" label="工具与劳保要求"><Input.TextArea rows={2} placeholder="安全帽、反光衣、安全鞋、工具清单等" /></Form.Item>
        <Form.Item name="safety_requirements" label="现场安全要求"><Input.TextArea rows={2} placeholder="如：禁止吸烟、动火需审批、指定行走路线" /></Form.Item>
        <Form.Item name="vehicle_access" label="车辆通行"><Input placeholder="如：货车提前一天报备，从3号门进" /></Form.Item>
        <Form.Item name="network_access" label="网络接入"><Input placeholder="网络、IP分配、VPN及甲方电脑限制" /></Form.Item>
        <Form.Item name="notes" label="补充说明"><Input.TextArea rows={3} /></Form.Item>
        {entryError && <Typography.Paragraph type="danger" role="alert">{entryError}</Typography.Paragraph>}
      </Form>
    </Drawer>

    <Modal className="field-work-modal" title={editingIndex == null ? '添加联系人' : '编辑联系人'} open={contactOpen} onCancel={() => { if (!contactSaving) setContactOpen(false) }} onOk={() => contactForm.submit()} confirmLoading={contactSaving} cancelButtonProps={{ disabled: contactSaving }} okText="保存" width={620}>
      <Form form={contactForm} layout="vertical" onFinish={submitContact}>
        <Row gutter={12}><Col xs={24} sm={12}><Form.Item name="department" label="甲方部门"><Input placeholder="如设备部" /></Form.Item></Col><Col xs={24} sm={12}><Form.Item name="team" label="小组 / 班组"><Input placeholder="如自动化组" /></Form.Item></Col></Row>
        <Row gutter={12}><Col xs={24} sm={8}><Form.Item name="name" label="姓名" rules={[{ required: true }]}><Input /></Form.Item></Col><Col xs={24} sm={8}><Form.Item name="title" label="职务"><Input /></Form.Item></Col><Col xs={24} sm={8}><Form.Item name="phone" label="电话"><Input /></Form.Item></Col></Row>
        <Form.Item name="email" label="邮箱"><Input /></Form.Item>
        <Form.Item name="responsibility" label="负责事项"><Input placeholder="如 网络协调、现场安全、设备验收" /></Form.Item>
        <Form.Item name="decision_scope" label="决策 / 签字范围"><Input placeholder="如 方案确认、停机窗口、初验签字" /></Form.Item>
        <Form.Item name="is_primary" label="联系人类型"><Select options={[{ value: true, label: '主联系人' }, { value: false, label: '普通联系人' }]} /></Form.Item>
        <Form.Item name="notes" label="备注"><Input.TextArea rows={2} /></Form.Item>
      </Form>
    </Modal>
  </div>
}
