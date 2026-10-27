import { Alert, Typography } from 'antd'

/** T40 weekly plans can consume the same Project coverage metadata. */
export default function HolidayCalendarNotice({ years, settingsLink = true }: { years?: number[]; settingsLink?: boolean }) {
  if (!years?.length) return null
  return <Alert type="warning" showIcon style={{ marginBottom: 12 }} message={`缺少 ${years.join('、')} 年节假日与调休数据`}
    description={<span>这些年份尚无已核对的全年安排，不能视为没有节假日。请待国务院公布后由管理员核对维护；目前仅按周休息和手动休息日处理。{settingsLink && <Typography.Link href="/pm/holidays">查看节假日设置</Typography.Link>}</span>} />
}
