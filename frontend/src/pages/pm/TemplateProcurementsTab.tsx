import { useEffect, useRef, useState } from 'react'
import { Alert, Card, Table, Typography, Tag, Space, Button, Select, Input, Modal, Form, Popconfirm, message } from 'antd'
import { PlusOutlined, DeleteOutlined, EditOutlined } from '@ant-design/icons'
import { IconAction } from '../../components/IconAction'
import { api } from '../../api/client'
import { useSubmitLock } from '../../hooks/useSubmitLock'

const RISK_LABEL: Record<string, string> = { low: '低', medium: '中', high: '高' }

/** 常用采购项库：项目经理在项目内显式勾选后才会带入；数量与到货状态在项目内维护。 */
export default function TemplateProcurementsTab({ templateId, editMode }: { templateId: string; editMode: boolean }) {
  const [items, setItems] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const [saving, setSaving] = useState(false)
  const requestSeq = useRef(0)
  const templateRef = useRef(templateId)
  templateRef.current = templateId
  const writeLock = useSubmitLock()
  const [modalOpen, setModalOpen] = useState(false)
  const [edit, setEdit] = useState<any | null>(null)
  const [form] = Form.useForm()

  const load = async () => {
    if (templateRef.current !== templateId) return
    const request = ++requestSeq.current
    setLoading(true); setLoadError(false)
    try {
      const result = await api.get(`/templates/${templateId}/procurements`)
      if (request === requestSeq.current) setItems(result.data)
    } catch { if (request === requestSeq.current) { setItems([]); setLoadError(true) } }
    finally { if (request === requestSeq.current) setLoading(false) }
  }
  useEffect(() => {
    setItems([]); setModalOpen(false); void load()
    return () => { requestSeq.current += 1 }
  }, [templateId])

  const save = async (v: any) => {
    if (!writeLock.tryAcquire()) return
    setSaving(true)
    try {
      if (edit) {
        await api.put(`/templates/${templateId}/procurements/${edit.id}`, v)
      } else {
        await api.post(`/templates/${templateId}/procurements`, v)
      }
      if (templateRef.current !== templateId) return
      message.success('已保存')
      setModalOpen(false)
      load()
    } catch (e: any) {
      message.error(e.response?.data?.detail ?? '保存失败')
    } finally { setSaving(false); writeLock.release() }
  }

  const remove = async (id: string) => {
    if (!writeLock.tryAcquire()) return
    setSaving(true)
    try {
      await api.delete(`/templates/${templateId}/procurements/${id}`)
      if (templateRef.current === templateId) { message.success('已删除'); await load() }
    } catch (e: any) { message.error(e.response?.data?.detail ?? '删除失败，记录已保留') }
    finally { setSaving(false); writeLock.release() }
  }

  return (
    <Card size="small">
      {loadError && <Alert type="error" showIcon message="清单加载失败" action={<Button onClick={() => void load()}>重试</Button>} style={{ marginBottom: 12 }} />}
      <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 12, flexWrap: 'wrap' }}>
        <Space direction="vertical" size={2}>
          <Typography.Text strong style={{ fontSize: 13 }}>
            常用采购项库
          </Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            只维护物料名称、规格和单位；数量与「到没到货」在项目准备页维护
          </Typography.Text>
        </Space>
        {editMode && (
          <Button size="small" type="primary" icon={<PlusOutlined />}
            onClick={() => {
              setEdit(null)
              form.resetFields()
              form.setFieldsValue({ unit: '台', is_required: false, risk: 'low' })
              setModalOpen(true)
            }}>
            添加常用项
          </Button>
        )}
      </Space>
      <Table
        loading={loading}
        scroll={{ x: 'max-content' }}
        rowKey="id"
        dataSource={items}
        size="small"
        pagination={false}
        columns={[
          {
            title: '物料', dataIndex: 'name',
            render: (v: string, t: any) => (
              <Space size={6}>
                <span style={{ fontWeight: 500 }}>{v}</span>
                {t.is_required && <Tag color="red" style={{ fontSize: 10 }}>通常必需</Tag>}
              </Space>
            ),
          },
          {
            title: '单位', dataIndex: 'unit', width: 80,
            render: (v: string) => <Tag style={{ fontSize: 10 }}>{v || '件'}</Tag>,
          },
          {
            title: '规格/型号', dataIndex: 'spec', ellipsis: true,
            render: (v: string) => <Typography.Text type="secondary" style={{ fontSize: 12 }}>{v || '—'}</Typography.Text>,
          },
          {
            title: '风险', dataIndex: 'risk', width: 70,
            render: (v: string) => <Tag color={v === 'high' ? 'red' : v === 'medium' ? 'orange' : 'green'}>{RISK_LABEL[v] ?? v}</Tag>,
          },
          ...(editMode ? [{
            title: '操作', width: 80,
            render: (_: any, t: any) => (
              <span className="row-icon-actions">
                <IconAction label="编辑采购项" icon={<EditOutlined />} onClick={() => { setEdit(t); form.setFieldsValue(t); setModalOpen(true) }} />
                <Popconfirm title="删除该采购项？" onConfirm={() => remove(t.id)}>
                  <IconAction label="删除采购项" icon={<DeleteOutlined />} danger />
                </Popconfirm>
              </span>
            ),
          }] : []),
        ]}
      />

      <Modal
        title={edit ? '编辑采购项' : '添加采购项'}
        open={modalOpen}
        onCancel={() => { if (!saving) setModalOpen(false) }}
        confirmLoading={saving}
        cancelButtonProps={{ disabled: saving }}
        onOk={() => form.submit()}
        okText="保存"
        width={480}
      >
        <Form form={form} layout="vertical" disabled={saving} onFinish={save}>
          <Form.Item name="name" label="物料名称" rules={[{ required: true }]}>
            <Input placeholder="如：车载工控机 / 自动充电桩 / 安全围栏" />
          </Form.Item>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            <Form.Item name="unit" label="单位">
              <Select style={{ width: 100 }} options={['台', '套', '米', '箱', '卷', '个', '件'].map((u) => ({ label: u, value: u }))} />
            </Form.Item>
            <Form.Item name="risk" label="风险">
              <Select style={{ width: 90 }} options={Object.entries(RISK_LABEL).map(([v, l]) => ({ label: l, value: v }))} />
            </Form.Item>
          </div>
          <Form.Item name="spec" label="规格/型号/说明">
            <Input placeholder="如：含 4G 模块与硬盘（每车 1 台）" />
          </Form.Item>
          <Form.Item name="is_required" label="通常必需">
            <Select style={{ width: 130 }} options={[{ label: '通常必需', value: true }, { label: '按需选择', value: false }]} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}
