import { useAuth } from '../../stores/auth'
import { hasSystemPermission } from '../../constants/systemPermissions'
import { WorkPageHeader, WorkSection } from '../../components/WorkPage'
import { NAV_LABEL, NAV_DESCRIPTION } from '../../constants/nav'
import './SettingsPages.css'
import { useEffect, useRef, useState } from 'react'
import {
  Button, Form, Input, message, Modal, Select, Space, Switch, Table, Tag, Typography,
} from 'antd'
import { ArrowDownOutlined, ArrowUpOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons'
import { vehicleTypeApi } from '../../api'
import { errMsg } from '../../api/client'
import { useSubmitLock } from '../../hooks/useSubmitLock'
import { IconAction } from '../../components/IconAction'

interface VehicleTypeRow {
  id: string
  name: string
  is_enabled: boolean
  sort_order: number
}

/** 车型字典管理（HYPE-63）：管理员集中新增 / 停用 / 排序 / 重命名。
 *  普通用户的项目创建、现场信息从启用项中选择，不再硬编码。
 *  停用仅隐藏于普通用户选择；被引用的车型禁止重命名（后端强制，提示「新建 + 停用旧项」）。 */
export default function VehicleTypesPage() {
  const { user } = useAuth()
  const canManage = hasSystemPermission(user, 'system.vehicle_types.manage')
  const [rows, setRows] = useState<VehicleTypeRow[]>([])
  const [loading, setLoading] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>()
  const [saving, setSaving] = useState(false)
  const [addOpen, setAddOpen] = useState(false)
  const [renameRow, setRenameRow] = useState<VehicleTypeRow | null>(null)
  const [addForm] = Form.useForm()
  const [renameForm] = Form.useForm()

  const submitLock = useSubmitLock()
  const busy = useRef(false)
  const dialog = useRef<'add' | string | null>(null)
  const scope = useRef(0)
  const loadSequence = useRef(0)

  const load = async () => {
    const request = ++loadSequence.current
    setLoading(true)
    try {
      const data = await vehicleTypeApi.listAll()
      if (request === loadSequence.current) setRows(data)
    } catch (error) {
      if (request === loadSequence.current) message.error(errMsg(error))
    } finally { if (request === loadSequence.current) setLoading(false) }
  }
  useEffect(() => {
    void load()
    return () => { scope.current++; loadSequence.current++; dialog.current = null }
  }, [])

  const mutate = async (action: () => Promise<void>) => {
    if (!canManage || !submitLock.tryAcquire()) return
    const generation = scope.current
    busy.current = true
    setSaving(true)
    loadSequence.current++
    setLoading(false)
    try { await action() }
    catch (error) { if (generation === scope.current) message.error(errMsg(error)) }
    finally {
      submitLock.release()
      busy.current = false
      if (generation === scope.current) setSaving(false)
    }
  }

  const add = async (values: any) => {
    if (dialog.current !== 'add') return
    const generation = scope.current
    await mutate(async () => {
      await vehicleTypeApi.create({ name: values.name })
      if (generation !== scope.current) return
      message.success('车型已添加')
      addForm.resetFields()
      dialog.current = null
      setAddOpen(false)
      await load()
    })
  }

  const rename = async (values: any) => {
    if (!renameRow || dialog.current !== renameRow.id) return
    const generation = scope.current
    await mutate(async () => {
      await vehicleTypeApi.update(renameRow.id, { name: values.name })
      if (generation !== scope.current) return
      setRows((current) => current.map((row) => row.id === renameRow.id ? { ...row, name: values.name } : row))
      message.success('已重命名')
      dialog.current = null
      setRenameRow(null)
      await load()
    })
  }

  const toggle = async (row: VehicleTypeRow, enabled: boolean) => {
    const generation = scope.current
    await mutate(async () => {
      await vehicleTypeApi.update(row.id, { is_enabled: enabled })
      if (generation !== scope.current) return
      setRows((current) => current.map((item) => item.id === row.id ? { ...item, is_enabled: enabled } : item))
      message.success(enabled ? '已启用' : '已停用')
      await load()
    })
  }

  const move = async (index: number, dir: -1 | 1) => {
    const target = index + dir
    if (target < 0 || target >= rows.length) return
    const next = [...rows]
    ;[next[index], next[target]] = [next[target], next[index]]
    const generation = scope.current
    await mutate(async () => {
      await vehicleTypeApi.reorder(next.map((r) => r.id))
      if (generation !== scope.current) return
      setRows(next)
      await load()
    })
  }

  const closeDialog = () => {
    if (busy.current) return
    dialog.current = null
    setAddOpen(false)
    setRenameRow(null)
  }

  const enabledCount = rows.filter((r) => r.is_enabled).length

  const visibleRows = rows.filter(row => row.name.toLowerCase().includes(keyword.trim().toLowerCase()) && (!statusFilter || String(row.is_enabled) === statusFilter))

  return (
    <div className="settings-work-page">
      <WorkPageHeader title={NAV_LABEL['/pm/vehicle-types']} description={NAV_DESCRIPTION['/pm/vehicle-types']}
        meta={`${rows.length} 种车型 · ${enabledCount} 种启用`}
        primary={canManage && <Button type="primary" icon={<PlusOutlined />} disabled={!canManage || saving || loading} onClick={() => { if (busy.current) return; dialog.current = 'add'; addForm.resetFields(); setAddOpen(true) }}>添加车型</Button>} />

      <WorkSection title="可选车型" description="停用只影响新选择；已用车型继续保留在历史项目。" filters={<Space wrap>
        <Input.Search placeholder="搜索车型" aria-label="搜索车型" allowClear value={keyword} onChange={event => setKeyword(event.target.value)} />
        <Select aria-label="按车型状态筛选" placeholder="全部状态" allowClear value={statusFilter} onChange={setStatusFilter} options={[{ value: 'true', label: '启用' }, { value: 'false', label: '已停用' }]} />
      </Space>}>
        <Table<VehicleTypeRow>
          rowKey="id"
          loading={loading}
          dataSource={visibleRows}
          scroll={{ x: 560 }}
          pagination={false}
          columns={[
            {
              title: '排序', width: 84,
              render: (_: any, row) => (
                <Space size={0}>
                  <Button size="small" type="text" icon={<ArrowUpOutlined />} disabled={!canManage || saving || loading || rows.findIndex(item => item.id === row.id) === 0} onClick={() => move(rows.findIndex(item => item.id === row.id), -1)} aria-label="上移" />
                  <Button size="small" type="text" icon={<ArrowDownOutlined />} disabled={!canManage || saving || loading || rows.findIndex(item => item.id === row.id) === rows.length - 1} onClick={() => move(rows.findIndex(item => item.id === row.id), 1)} aria-label="下移" />
                </Space>
              ),
            },
            { title: '车型', dataIndex: 'name', render: (v: string) => <Typography.Text strong>{v}</Typography.Text> },
            {
              title: '状态', dataIndex: 'is_enabled', width: 130,
              render: (v: boolean, row) => (
                <Space size={8}>
                  <Switch size="small" checked={v} disabled={!canManage || saving || loading} onChange={(checked) => toggle(row, checked)} />
                  <Tag color={v ? 'green' : 'default'}>{v ? '启用' : '已停用'}</Tag>
                </Space>
              ),
            },
            {
              title: '操作', width: 110,
              render: (_: any, row) => (
                <IconAction label="重命名" icon={<EditOutlined />}
                  disabled={!canManage || saving || loading} onClick={() => { if (busy.current) return; dialog.current = row.id; renameForm.setFieldsValue({ name: row.name }); setRenameRow(row) }} />
              ),
            },
          ]}
        />
        <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
          停用后，历史数据中该车型仍会正常显示（编辑时以「（历史）」保留）；被引用的车型禁止重命名，可新建替代车型后停用旧项。
        </Typography.Text>
      </WorkSection>

      <Modal title="添加车型" open={addOpen} onCancel={closeDialog} cancelButtonProps={{ disabled: saving }} closable={!saving} maskClosable={!saving} keyboard={!saving} onOk={() => addForm.submit()} okText="添加" confirmLoading={saving} okButtonProps={{ disabled: !canManage }}>
        <Form form={addForm} disabled={!canManage || saving} layout="vertical" onFinish={add}>
          <Form.Item name="name" label="车型名称" rules={[{ required: true, message: '请输入车型名称' }]}>
            <Input maxLength={50} placeholder="如：双向车 / 背负式" />
          </Form.Item>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            名称将出现在所有项目创建的车型选择中；空名与重复名称会被拒绝。
          </Typography.Text>
        </Form>
      </Modal>

      <Modal title={`重命名「${renameRow?.name ?? ''}」`} open={!!renameRow} onCancel={closeDialog} cancelButtonProps={{ disabled: saving }} closable={!saving} maskClosable={!saving} keyboard={!saving} onOk={() => renameForm.submit()} okText="保存" confirmLoading={saving} okButtonProps={{ disabled: !canManage }}>
        <Form form={renameForm} disabled={!canManage || saving} layout="vertical" onFinish={rename}>
          <Form.Item name="name" label="车型名称" rules={[{ required: true, message: '请输入车型名称' }]}>
            <Input maxLength={50} />
          </Form.Item>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            已被项目车辆或模板任务引用的车型禁止重命名；此时请新建替代车型并停用旧项，历史数据不受影响。
          </Typography.Text>
        </Form>
      </Modal>
    </div>
  )
}
