/** 每个项目状态的一句话说明。状态由负责人按实际情况手动推进，系统不核对资料。 */
export interface StageGuidance { next?: string; description: string }

const STAGES: Record<string, StageGuidance> = {
  preparing: { next: 'executing', description: '补充客户、车型和周计划；人员到场后推进到现场实施。' },
  executing: { next: 'acceptance', description: '在本周页登记现场工作，问题随时上报；现场工作结束后推进到验收中。' },
  acceptance: { next: 'completed', description: '录入验收结论、上传签单；客户确认后推进到已完成。' },
  completed: { next: 'archived', description: '补齐交付资料，填写复盘后归档。' },
  archived: { description: '项目已归档，资料和记录都可以随时查阅。' },
  suspended: { description: '停工原因处理后，恢复到停工前的状态。' },
}

export function projectStageGuidance(status: string): StageGuidance | null {
  return STAGES[status] ?? null
}
