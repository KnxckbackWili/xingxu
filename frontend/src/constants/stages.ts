/** The stage backbone shared by templates and projects (company document stages 4–9; backend app/services/template_stages.py). */
export const STAGES = [
  { key: '4', name: '内部启动会' },
  { key: '5', name: '发车前' },
  { key: '6', name: '实施' },
  { key: '7', name: '验收' },
  { key: '8', name: '交付' },
  { key: '9', name: '全项目周期' },
] as const
export const STAGE_NAME: Record<string, string> = Object.fromEntries(STAGES.map(stage => [stage.key, stage.name]))
export const stageLabel = (key?: string | null) => key && STAGE_NAME[key] ? `${key} · ${STAGE_NAME[key]}` : '未归阶段'
export const stageIndex = (key?: string | null) => { const index = STAGES.findIndex(stage => stage.key === key); return index < 0 ? STAGES.length : index }
