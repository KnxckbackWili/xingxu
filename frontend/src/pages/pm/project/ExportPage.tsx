import { ProjectCapabilitiesContext, hasProjectCapability, useProjectWriteBlocked } from '../../../hooks/useProjectCapability'
import { useAuth } from '../../../stores/auth'
import { hasSystemPermission } from '../../../constants/systemPermissions'
import { Card, Button, Space, Typography, message, Form, Input, DatePicker, Modal, Collapse, Divider } from 'antd'
import { FileZipOutlined, FileExcelOutlined, FileDoneOutlined, CopyOutlined, BarChartOutlined } from '@ant-design/icons'
import { api } from '../../../api/client'
import { useNavigate } from 'react-router-dom'
import { useContext, useEffect, useRef, useState } from 'react'
import { useSubmitLock } from '../../../hooks/useSubmitLock'
import dayjs from 'dayjs'
import ProjectJsonImport from '../../../components/ProjectJsonImport'

import { parseDispositionFilename } from '../../../utils/download'
import { WorkPageHeader } from '../../../components/WorkPage'
import './FieldWorkPages.css'

/** 兜底文件名：安全化项目名_YYYY-MM-DD.ext（与后端同一规则）。 */
function fallbackExportName(projectName: string, ext: string): string {
  const sanitized = (projectName || '')
    .replace(/[/\\:*?"<>|]/g, '_')
    .replace(/^[\s.]+|[\s.]+$/g, '')
    .slice(0, 80)
    .trim() || '项目'
  return `${sanitized}_${dayjs().format('YYYY-MM-DD')}.${ext}`
}

/** 项目导出：推荐「导出项目包」ZIP，其余高级能力收起。 */
export default function ExportPage({ projectId, projectName = '' }: { projectId: string; projectName?: string }) {
  const { user } = useAuth()
  const canCreate = hasSystemPermission(user, 'projects.create')
  const writeBlocked = useProjectWriteBlocked()
  const canClone = hasProjectCapability(useContext(ProjectCapabilitiesContext), 'project.update', canCreate) && canCreate && !writeBlocked
  const navigate = useNavigate()
  const cloneLock = useSubmitLock()
  const activeProject = useRef(projectId)
  activeProject.current = projectId
  const active = useRef(true)
  useEffect(() => { active.current = true; return () => { active.current = false } }, [projectId])
  const [cloneOpen, setCloneOpen] = useState(false)
  const [cloning, setCloning] = useState(false)
  const [form] = Form.useForm()
  const download = async (url: string, ext: string) => {
    try {
      const r = await api.get(url, { responseType: 'blob', timeout: 600000 })
      // HYPE-71：优先使用响应头里的文件名（安全化项目名_日期.ext），解析失败才用本地兜底
      const headerName = parseDispositionFilename(r.headers?.['content-disposition'])
      const name = headerName || fallbackExportName(projectName, ext)
      const u = URL.createObjectURL(r.data); const a = document.createElement('a'); a.href = u; a.download = name; a.click(); URL.revokeObjectURL(u)
      message.success('导出成功')
    } catch { message.error('导出失败') }
  }

  const printWeeklyPlan = () => {
    window.open(`/pm/projects/${projectId}/plan?view=weeks`, '_blank')
    message.info('新窗口打开周计划，按 Ctrl+P 保存为 PDF')
  }

  const doClone = async (values: any) => {
    if (!canClone || !cloneLock.tryAcquire()) return
    setCloning(true)
    try {
      const r = await api.post(`/projects/${projectId}/clone`, {
        name: values.name,
        start_date: values.range[0].format('YYYY-MM-DD'),
        end_date: values.range[1].format('YYYY-MM-DD'),
      })
      if (active.current && activeProject.current === projectId) { message.success(r.data.message); setCloneOpen(false); navigate(`/pm/projects/${r.data.id}`) }
    } catch (e: any) { message.error(e.response?.data?.detail ?? '克隆失败') } finally { cloneLock.release(); if (active.current && activeProject.current === projectId) setCloning(false) }
  }

  return (
    <div className="field-work-page">
      <WorkPageHeader title="项目导出" description="保存完整项目包，方便备份、迁移或交接。需要复用工作内容时，可在其他工具中克隆项目。"
        primary={<Button type="primary" icon={<FileZipOutlined />} onClick={() => download(`/projects/${projectId}/export/package`, 'zip')}>导出项目包（推荐）</Button>} />
      <Card size="small" title="导出与复用">
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          <Space wrap>
            <Typography.Text type="secondary">完整项目包包含项目资料、工作项与周计划、附件、验收及复盘记录。</Typography.Text>
          </Space>
          <Space wrap>
            <Button icon={<FileExcelOutlined />} onClick={() => download(`/projects/${projectId}/export/lifecycle`, 'AGV生命周期表.xlsx')}>导出生命周期表</Button>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>按原版版式导出车辆问题履历，可存档、打印或修改后重新导入</Typography.Text>
          </Space>
          <Divider style={{ margin: '4px 0' }} />
          <Collapse
            ghost
            defaultActiveKey={[]}
            items={[{
              key: 'advanced',
              label: '高级：结构化快照与克隆',
              children: (
                <Space direction="vertical" size={10} style={{ width: '100%' }}>
                  <Space wrap>
                    <Button icon={<FileExcelOutlined />} onClick={() => download(`/projects/${projectId}/export/excel`, 'xlsx')}>导出 Excel</Button>
                    <Button icon={<FileDoneOutlined />} onClick={() => download(`/projects/${projectId}/export/json`, 'json')}>导出 JSON 快照</Button>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>Excel 默认6张交付表；JSON 结构化快照用于新建项目。完整恢复使用设置中的加密备份。</Typography.Text>
                  </Space>
                  <ProjectJsonImport projectId={projectId} />
                  <Space wrap>
                    <Button icon={<BarChartOutlined />} onClick={printWeeklyPlan}>周计划 PDF</Button>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>新窗口打开周计划，按 Ctrl+P 保存为 PDF</Typography.Text>
                  </Space>
                  {canClone && <Space wrap>
                    <Button icon={<CopyOutlined />} onClick={() => setCloneOpen(true)}>克隆本项目</Button>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>复制车型和工作项结构生成全新项目（不复制进度）</Typography.Text>
                  </Space>}
                </Space>
              ),
            }]}
          />
        </Space>
      </Card>

      <Modal className="field-work-modal" title="克隆项目" open={cloneOpen} onCancel={() => { if (!cloning) setCloneOpen(false) }} onOk={() => form.submit()} confirmLoading={cloning}>
        <Form form={form} layout="vertical" onFinish={doClone}>
          <Form.Item name="name" label="新项目名称" rules={[{ required: true }]}><Input placeholder="例如：华东物流中心 AGV 二期" /></Form.Item>
          <Form.Item name="range" label="新实施周期" rules={[{ required: true }]}><DatePicker.RangePicker style={{ width: '100%' }} /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
