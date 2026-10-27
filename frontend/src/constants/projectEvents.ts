import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
import timezone from 'dayjs/plugin/timezone'

dayjs.extend(utc)
dayjs.extend(timezone)

export const PROJECT_EVENT_LABELS: Record<string, string> = {
  internal_kickoff: '内部启动会', ship: '发车', arrival_all: '全部到场', delivery_signed: '到货签收',
  commissioning_done: '调试完工', go_live: '上线运行', training_done: '培训完成', acceptance: '项目验收', handover: '交付售后',
}
export const PLAN_EVENTS = ['internal_kickoff', 'ship', 'arrival_all'] as const
export const DISPATCH_PLATFORMS = [{ value: 'NDC', label: 'NDC' }, { value: 'GRACE', label: 'GRACE' }, { value: 'integrated', label: '集成' }]
export type ProjectEvent = {
  id?: string | null; event_key: string; label: string; planned_date?: string | null; actual_at?: string | null
  actual_source?: { kind?: string; time_basis?: string }; source_description?: string
  actual_date?: string | null; actual_precision: 'date' | 'datetime'; derived: boolean; note?: string
}
export const plannedDate = (project: { events?: ProjectEvent[] }, key: string) => project.events?.find(event => event.event_key === key)?.planned_date ?? null
export const planFormValues = (project: { events?: ProjectEvent[] }) => Object.fromEntries(PLAN_EVENTS.map(key => [key, plannedDate(project, key) ? dayjs(plannedDate(project, key)) : null]))
export const planPayload = (values: Record<string, dayjs.Dayjs | null> = {}) => Object.fromEntries(PLAN_EVENTS.map(key => [key, values[key]?.format('YYYY-MM-DD') ?? null]))

export const inProjectTime = (value: string | undefined, zone: string) => dayjs(value).tz(zone)
