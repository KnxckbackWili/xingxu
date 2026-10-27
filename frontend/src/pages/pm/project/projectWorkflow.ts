import { isProjectStatus } from '../../../constants/status'

/** 启动清单只提供导航；状态流转仍由服务端检查准备、验收与权限。 */
export interface WorkflowInput {
  status: string
  vehicles: number
  tasks: number
  members: number
  plans: number | null
  drafts: number | null
  unassigned: number | null
  planWarnings?: number
  prepReady: boolean
  kickoffReady?: boolean
  severeIssues: number
  progress: number
}
export interface WorkflowAction { title: string; description: string; path: string; status?: string }

export function projectStageGuidance(status: string): { next?: string; description: string; path: string; link: string } | null {
  const stages: Record<string, { next?: string; description: string; path: string; link: string }> = {
    preparing: { next: 'ready', description: '按顺序核对车型、人员、资料、周计划和发车前资料。第4阶段必需资料齐备后，由负责人确认待进场。', path: '/documents?stage=4', link: '核对筹备资料' },
    ready: { next: 'executing', description: '发车前资料齐备，或已有仍然有效的风险批准后，负责人确认开始现场实施。进场前可提交资料和上报问题。', path: '/documents?review=1', link: '发车前资料确认' },
    executing: { next: 'acceptance', description: '联调和试运行按关键事件记录；提交到货签收单、调试完工单、上线运行单和培训记录后，负责人确认进入验收中。', path: '/documents?stage=6', link: '核对签单资料' },
    acceptance: { next: 'completed', description: '核对完成进度、质量检查、必需资料、已关闭或作废的问题、车辆故障和最新有效验收，再人工确认完成。', path: '/documents?acceptance=1', link: '核对验收记录' },
    completed: { next: 'archived', description: '补齐交付和全周期资料并填写复盘，重新核对完成依据后归档。', path: '/documents', link: '核对归档资料' },
    archived: { description: '项目已归档，可查阅原资料和历史记录；整改需先恢复状态，原证据保留。', path: '/documents', link: '查看交付资料' },
    suspended: { description: '处理停工原因后，负责人明确恢复原阶段；填报、撤回和资料上传不会自行恢复项目。', path: '/issues', link: '查看停工问题' },
  }
  return stages[status] ?? null
}

export function projectWorkflow(x: WorkflowInput) {
  const checklist = [
    { title: '车型', description: x.vehicles ? `${x.vehicles} 台已配置` : '确认车型和台数', path: '/edit?section=vehicles', done: x.vehicles > 0 },
    { title: '人员', description: x.members ? `${x.members} 人已加入` : '确认参与人员', path: '/edit?section=members', done: x.members > 0 },
    { title: '资料清单', description: x.kickoffReady ? '第4阶段必需资料齐备' : '提交筹备资料或说明不适用理由', path: '/documents?stage=4', done: x.kickoffReady === true },
    { title: '周计划', description: x.plans===null ? '周计划尚未读取，请重新核对' : x.plans ? `${x.plans} 格周计划${x.drafts===null?'':`，${x.drafts} 格草稿`}` : '核对本周工作和负责人', path: '/plan?view=weeks', done: x.plans!==null && x.plans>0 && x.drafts===0 && x.unassigned===0 && !x.planWarnings },
    { title: '发车前资料确认', description: x.prepReady ? '资料确认已就绪' : '核对第5阶段资料与风险批准', path: '/documents?review=1', done: x.prepReady },
  ]
  const setup = ['preparing', 'ready'].includes(x.status)
  const guidance = projectStageGuidance(x.status)
  let action: WorkflowAction
  if (!isProjectStatus(x.status)) action = { title: '查阅历史记录', description: `原始状态为「${x.status || '空值'}」，请管理员根据备份和审计核对。`, path: '/activity' }
  else if (x.status === 'preparing') {
    const next = checklist.find(item => !item.done)
    action = next ? { title: next.title, description: next.description, path: next.path }
      : { title: '确认待进场', description: '系统会重新核对第4阶段必需资料。', path: '/documents?stage=4', status: 'ready' }
  } else if (x.status === 'ready') action = x.prepReady ? { title: '确认开始现场实施', description: guidance!.description, path: guidance!.path, status: 'executing' } : { title: '发车前资料确认', description: guidance!.description, path: guidance!.path }
  else if (['executing', 'acceptance'].includes(x.status) && x.severeIssues > 0) action = { title: '处理严重问题', description: `有 ${x.severeIssues} 个严重问题，请先评估影响。`, path: '/issues' }
  else if (x.status === 'executing') action = x.progress >= 100 ? { title: '核对签单与验收', description: guidance!.description, path: guidance!.path } : { title: '跟进现场实施', description: '查看本周工作与执行人，签单齐备后由负责人推进验收。', path: '/plan?view=weeks' }
  else action = { title: guidance?.link ?? '查看项目', description: guidance?.description ?? '', path: guidance?.path ?? '/overview' }
  return { checklist, setup, action }
}
