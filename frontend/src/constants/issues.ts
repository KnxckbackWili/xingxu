/** 问题类型 + 上报提示 + 分类专属字段（因地制宜 AGV 场景） */
export const ISSUE_NATURES = [{value:'normal',label:'普通'},{value:'accident',label:'事故'},{value:'quality',label:'质量问题'}]
export const ISSUE_TYPES = [
  { label: '🛠 硬件问题（车辆/充电/传感器）', value: 'hardware' },
  { label: '💻 软件问题（调度/地图/联调）', value: 'software' },
  { label: '🏭 环境问题（网络/地面/现场）', value: 'environment' },
  { label: '📋 流程问题（接口/资料/协调）', value: 'process' },
  { label: '⚠️ 安全隐患', value: 'safety' },
  { label: '其他', value: 'other' },
]

export const ISSUE_TYPE_SHORT: Record<string, string> = {
  hardware: '硬件', software: '软件', environment: '环境', process: '流程', safety: '安全', other: '其他',
}

export const ISSUE_TYPE_HINTS: Record<string, string> = {
  hardware: '硬件问题：请提供车辆/设备编号、故障现象、发生时间',
  software: '软件问题：请提供操作步骤、报错信息、影响的功能',
  environment: '环境问题：请提供位置、现象、现场照片',
  process: '流程问题：请说明卡在哪一步、缺什么资料',
  safety: '安全隐患：请立即说明风险点、涉及人员、现场位置',
  other: '其他：请简述情况',
}

/** 分类专属字段：按问题类型动态渲染的表单字段（value 存入后端 extra） */
export interface IssueTypeField {
  key: string
  label: string
  type: 'input' | 'select'
  options?: { label: string; value: string }[]
  placeholder?: string
}

export const ISSUE_TYPE_FIELDS: Record<string, IssueTypeField[]> = {
  hardware: [
    { key: 'device', label: '设备/部位', type: 'input', placeholder: '如：AGV-01 充电桩 / 导航激光头 / 电池箱' },
    {
      key: 'affects_schedule', label: '是否影响工期', type: 'select',
      options: [{ label: '影响，需调整计划', value: '影响' }, { label: '不影响', value: '不影响' }],
    },
  ],
  software: [
    { key: 'module_version', label: '涉及模块/版本', type: 'input', placeholder: '如：调度系统 v2.1 / 地图编辑器 / PLC 程序' },
  ],
  process: [
    { key: 'dept_contact', label: '涉及部门/接口人', type: 'input', placeholder: '如：客户信息部 / 王工（电气接口）' },
  ],
  environment: [],
  safety: [],
  other: [],
}

/** 把 extra 字段翻译为可读摘要：{device:'AGV-01', affects_schedule:'影响'} → "设备/部位：AGV-01 · 是否影响工期：影响"。
 *  只展示有中文标签的分类专属字段；未知键（如质量问题反馈单导入写入 extra 的 project_name/reporter_name 等）
 *  一律跳过，避免标题区泄漏原始字段名。 */
export function extraSummary(extra: Record<string, unknown> | null | undefined): string {
  if (!extra) return ''
  const labels: Record<string, string> = {}
  for (const fields of Object.values(ISSUE_TYPE_FIELDS)) {
    for (const f of fields) labels[f.key] = f.label
  }
  const parts = Object.entries(extra)
    .filter(([k, v]) => labels[k] && v !== null && v !== undefined && v !== '')
    .map(([k, v]) => `${labels[k]}：${v}`)
  return parts.join(' · ')
}

/** 问题状态唯一事实源（台账状态 Tag/筛选用；与后端 C6-3 状态机一致） */
export const ISSUE_STATUS_MAP: Record<string, { label: string; color: string }> = {
  open: { label: '待处理', color: 'red' },
  processing: { label: '处理中', color: 'orange' },
  resolved: { label: '已解决', color: 'green' },
  closed: { label: '已关闭', color: 'default' },
  cancelled: { label: '已作废', color: 'magenta' },
}
