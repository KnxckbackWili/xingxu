import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Card, Drawer, Select, Skeleton, Space, Tag, Typography } from 'antd'
import { LeftOutlined, RightOutlined } from '@ant-design/icons'
import dayjs, { Dayjs } from 'dayjs'
import { api } from '../../api/client'
import { useMediaQuery } from '../../hooks/useMediaQuery'
import { MEDIA_QUERY } from '../../constants/breakpoints'
import EmptyState from '../../components/EmptyState'
import { openWorkDetail } from '../../stores/workDetail'

interface TeamEntry {
  entry_id: string
  work_date: string
  assignee_id: string | null
  assignee_name: string
  project_id: string
  project_name: string
  task_id: string
  task_name: string
  planned_quantity: number
  completed_quantity: number
  // HYPE-91：当天明细展示字段（GET team-schedule 已返回，前端零后端改动）
  status: string
  is_confirmed: boolean
  is_locked: boolean
  notes: string | null
}

interface TeamPerson { id: string; name: string }

const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日']

/** 状态口径与「我的日程」一致：计划量>0 且完成量≥计划量才算完成；skipped 保持已跳过。 */
const ENTRY_STATUS: Record<string, { label: string; color: string }> = {
  planned: { label: '待执行', color: 'blue' },
  done: { label: '已完成', color: 'success' },
  skipped: { label: '已跳过', color: 'default' },
}

const entryStatus = (e: Pick<TeamEntry, 'planned_quantity' | 'completed_quantity' | 'status'>) => {
  if (e.planned_quantity > 0 && e.completed_quantity >= e.planned_quantity) return ENTRY_STATUS.done
  if (e.status === 'skipped') return ENTRY_STATUS.skipped
  return ENTRY_STATUS.planned
}

/** 月历网格起始：当月首日所在周之周一。 */
function gridStartFor(month: Dayjs): Dayjs {
  const first = month.startOf('month')
  const offset = first.day() === 0 ? 6 : first.day() - 1
  return first.subtract(offset, 'day')
}

/**
 * 团队日程（HYPE-88，只读）：PM 端查看「手下的人」的跨项目排班汇总。
 * 可见人集由服务端收敛（本人任项目经理/技术经理/协同管理员的项目中被排班或成员；
 * admin/director 全部）。本页不直接写日程；工作详情仍按对应项目能力开放调整。
 * HYPE-90：与 PM「我的日程」同口径，固定月历视图（无 列表⇄日历 切换）。
 */
export default function TeamSchedulePage() {
  const [entries, setEntries] = useState<TeamEntry[]>([])
  const [people, setPeople] = useState<TeamPerson[]>([])
  const [userFilter, setUserFilter] = useState<string | undefined>(undefined)
  const [month, setMonth] = useState<Dayjs>(dayjs())
  const [loading, setLoading] = useState(true)
  // HYPE-91：点日格查看当天明细（只读，与「我的日程」交互对齐）
  const [selectedDate, setSelectedDate] = useState<string>(dayjs().format('YYYY-MM-DD'))
  const [dayDrawer, setDayDrawer] = useState(false)
  const isMobile = useMediaQuery(MEDIA_QUERY.mobile)

  const [loadError, setLoadError] = useState(false)
  const loadSeq = useRef(0)
  const load = useCallback(async () => {
    const seq = ++loadSeq.current
    setLoading(true)
    setLoadError(false)
    try {
      const from = gridStartFor(month)
      const to = from.add(41, 'day')
      const r = await api.get('/dashboard/team-schedule', {
        params: {
          from_date: from.format('YYYY-MM-DD'),
          to_date: to.format('YYYY-MM-DD'),
          ...(userFilter ? { user_id: userFilter } : {}),
        },
      })
      if (seq !== loadSeq.current) return
      setEntries(r.data.entries ?? [])
      setPeople(r.data.people ?? [])
    } catch {
      if (seq === loadSeq.current) { setLoadError(true); setEntries([]) }
    } finally {
      if (seq === loadSeq.current) setLoading(false)
    }
  }, [month, userFilter])

  useEffect(() => { load(); return () => { loadSeq.current++ } }, [load])

  const gridStart = useMemo(() => gridStartFor(month), [month])
  const cells = useMemo(() => Array.from({ length: 42 }, (_, i) => gridStart.add(i, 'day')), [gridStart])
  const today = dayjs().format('YYYY-MM-DD')

  const byDate = useMemo(() => {
    const map = new Map<string, TeamEntry[]>()
    for (const e of entries) {
      if (!map.has(e.work_date)) map.set(e.work_date, [])
      map.get(e.work_date)!.push(e)
    }
    return map
  }, [entries])

  const renderEntry = (e: TeamEntry) => (
    <div key={e.entry_id} style={{
      fontSize: 11, lineHeight: 1.3, padding: '1px 4px', borderRadius: 4,
      background: 'var(--agv-primary-soft)', color: 'var(--agv-text)',
      borderLeft: '3px solid var(--agv-primary)',
      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
    }}>
      {e.assignee_name} · {e.task_name} · 计划 {e.planned_quantity}
    </div>
  )

  return (
    <div>
      <Typography.Title level={5} style={{ margin: '0 0 12px' }}>
        团队日程
        <Typography.Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
          {month.format('YYYY年M月')} · {entries.length} 项安排（只读）
        </Typography.Text>
      </Typography.Title>

      <Space style={{ marginBottom: 12, flexWrap: 'wrap' }} align="center">
        <Select
          allowClear
          placeholder="按人员过滤"
          style={{ minWidth: 160 }}
          value={userFilter}
          onChange={(v) => setUserFilter(v)}
          options={people.map((p) => ({ value: p.id, label: p.name }))}
        />
        <Space size={4}>
          <Button size="small" icon={<LeftOutlined />} aria-label="上一月" onClick={() => setMonth(month.subtract(1, 'month'))} />
          <Typography.Text style={{ width: 92, textAlign: 'center', fontSize: 13 }}>{month.format('YYYY年M月')}</Typography.Text>
          <Button size="small" icon={<RightOutlined />} aria-label="下一月" onClick={() => setMonth(month.add(1, 'month'))} />
        </Space>
      </Space>

      {loadError && <Alert type="error" showIcon message="团队日程加载失败" description="这不代表没有安排，请重新加载确认。" action={<Button onClick={load}>重新加载</Button>} style={{ marginBottom: 12 }} />}
      {loading ? (
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          {[1, 2, 3].map((i) => <Skeleton key={i} active paragraph={{ rows: 1 }} />)}
        </Space>
      ) : loadError ? null : entries.length === 0 ? (
        <EmptyState title="暂无团队日程" description="你管辖的项目里暂无排班数据。" />
      ) : (
        <Card size="small">
          <div className="schedule-calendar-grid">
            {WEEKDAYS.map((w, i) => (
              <div key={w} style={{
                textAlign: 'center', fontSize: 12, padding: '4px 0',
                color: i === 6 ? 'var(--agv-danger)' : 'var(--agv-text-secondary)', fontWeight: 600,
              }}>
                {w}
              </div>
            ))}
            {cells.map((d) => {
              const key = d.format('YYYY-MM-DD')
              const dayItems = byDate.get(key) ?? []
              const inMonth = d.month() === month.month()
              const isToday = key === today
              const isWeekend = d.day() === 0 || d.day() === 6
              return (
                <button type="button" className="schedule-calendar-day" key={key} data-date={key}
                  aria-label={`${key}，${dayItems.length} 项安排`} aria-current={isToday ? "date" : undefined} aria-pressed={dayDrawer && selectedDate === key}
                  onClick={() => { setSelectedDate(key); setDayDrawer(true) }}
                  style={{
                  minHeight: 88, borderRadius: 8,
                  border: key === today ? '1.5px solid var(--agv-primary)' : '1px solid var(--agv-border)',
                  background: inMonth ? (isWeekend ? 'var(--agv-bg-subtle)' : 'var(--agv-bg-container)') : 'var(--agv-bg-layout)',
                  padding: 3, overflow: 'hidden',
                  cursor: 'pointer',
                }}>
                  <div style={{
                    textAlign: 'right', fontSize: 12, padding: '0 2px',
                    color: !inMonth ? 'var(--agv-text-secondary)' : isToday ? 'var(--agv-on-primary)' : isWeekend ? 'var(--agv-danger)' : 'var(--agv-text)',
                    fontWeight: isToday ? 700 : 400,
                    background: isToday ? 'var(--agv-primary)' : 'transparent',
                    borderRadius: 8, display: 'inline-block', float: 'right', margin: 0,
                  }}>
                    {d.date()}
                  </div>
                  <span className="schedule-calendar-count">{dayItems.length} 项</span>
                  <div className="schedule-calendar-entries" style={{ display: 'flex', flexDirection: 'column', gap: 2, marginTop: 2, clear: 'both' }}>
                    {dayItems.slice(0, 2).map(renderEntry)}
                    {dayItems.length > 2 && (
                      <div style={{ fontSize: 10, color: 'var(--agv-text-secondary)', paddingLeft: 4 }}>
                        +{dayItems.length - 2} 项
                      </div>
                    )}
                  </div>
                </button>
              )
            })}
          </div>
        </Card>
      )}

      {/* HYPE-91：当天明细 Drawer（只读，与「我的日程」交互对齐） */}
      <Drawer
        title={`${selectedDate} 日程（${(byDate.get(selectedDate) ?? []).length} 条）`}
        open={dayDrawer}
        onClose={() => setDayDrawer(false)}
        width={isMobile ? '100%' : 420}
      >
        {(byDate.get(selectedDate) ?? []).length === 0 ? (
          <EmptyState compact title="当天没有日程" description="这一天没有安排排程任务。" />
        ) : (
          <Space direction="vertical" style={{ width: '100%' }} size={8}>
            {(byDate.get(selectedDate) ?? []).map((e) => {
              const st = entryStatus(e)
              return (
                <Card key={e.entry_id} size="small">
                  <Space direction="vertical" size={4} style={{ width: '100%' }}>
                    <Space size={6} wrap>
                      <Typography.Text strong>{e.assignee_name}</Typography.Text>
                      <Tag color={st.color}>{st.label}</Tag>
                      {e.is_confirmed ? <Tag color="green">已下达</Tag> : <Tag>未下达</Tag>}
                      {e.is_locked && <Tag color="warning">已锁定</Tag>}
                    </Space>
                    <Typography.Text style={{ fontSize: 13 }}>
                      {e.project_name} · {e.task_name}
                    </Typography.Text>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      计划 {e.planned_quantity} / 完成 {e.completed_quantity}
                    </Typography.Text>
                    {e.notes && (
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>备注：{e.notes}</Typography.Text>
                    )}
                    <Button size="small" className="touch-target" disabled={!e.project_id || !e.task_id} onClick={() => {
                      setDayDrawer(false)
                      openWorkDetail({ projectId: e.project_id, taskId: e.task_id, entryId: e.entry_id, onChanged: load })
                    }}>查看工作</Button>
                  </Space>
                </Card>
              )
            })}
          </Space>
        )}
      </Drawer>
    </div>
  )
}
