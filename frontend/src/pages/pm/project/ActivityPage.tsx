import Tabs from '../../../components/VisibleTabs'
import HistoryPage from './HistoryPage'
import ReportPage from './ReportPage'

export type ActivitySubKey = 'history' | 'reports'

/**
 * 项目动态（v1.2.1 信息架构重构）：
 * 变更记录（审计流水）+ 周期报告（周/月报）。
 *
 * 内页 Tab 与 URL 同步：sub 由 ProjectLayout 从地址栏解析传入
 * （/activity 默认落到变更记录，/reports 为周期报告），
 * 切换 Tab 时通过 onSubChange 更新地址栏。
 */
export default function ActivityPage({ projectId, projectName, sub, onSubChange, standalone = false }: { standalone?: boolean; projectId: string; projectName: string; sub: ActivitySubKey; onSubChange: (key: string) => void }) {
  if (standalone) return sub === 'history' ? <HistoryPage projectId={projectId} /> : <ReportPage projectId={projectId} projectName={projectName} />
  return (
    <Tabs
      activeKey={sub}
      onChange={onSubChange}
      items={[
        { key: 'history', label: '操作记录', children: <HistoryPage projectId={projectId} /> },
        { key: 'reports', label: '项目报告', children: <ReportPage projectId={projectId} projectName={projectName} /> },
      ]}
    />
  )
}
