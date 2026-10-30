import { Alert, Typography } from 'antd'

/** Missing official holiday years. `compact` is one quiet line for planning pages; the full form explains the fallback. */
export default function HolidayCalendarNotice({ years, settingsLink = true, compact = false }: { years?: number[]; settingsLink?: boolean; compact?: boolean }) {
  if (!years?.length) return null
  if (compact) return <Alert className="holiday-notice-compact" type="info" showIcon banner message={<span>缺少 {years.join('、')} 年节假日与调休数据，暂按周休息日排期。{settingsLink && <Typography.Link href="/pm/holidays">维护节假日</Typography.Link>}</span>} />
  return <Alert type="warning" showIcon style={{ marginBottom: 12 }} message={`缺少 ${years.join('、')} 年节假日与调休数据`}
    description={<span>这些年份尚无已核对的全年安排，不能视为没有节假日。请待国务院公布后由管理员核对维护；目前仅按周休息和手动休息日处理。{settingsLink && <Typography.Link href="/pm/holidays">查看节假日设置</Typography.Link>}</span>} />
}
