import Tabs from '../../../components/VisibleTabs'
import { Typography } from 'antd'
import { CarOutlined, ContactsOutlined, InboxOutlined } from '@ant-design/icons'
import type { Project } from '../../../api'
import VehicleLifecyclePage from './VehicleLifecyclePage'
import InventoryPage from './InventoryPage'
import SiteHandoverPage from './SiteHandoverPage'

export type SiteSubKey = 'vehicles' | 'inventory' | 'handover'

/**
 * 现场信息（现场车辆 / 物品与去向 / 现场交接）。
 * 内页 Tab 与 URL 同步：sub 由 ProjectLayout 从地址栏解析传入
 * （/vehicles、/inventory、/handover），切换 Tab 时通过 onSubChange 更新地址栏，
 * 浏览器前进/后退与深链刷新后选中态保持一致。
 */
export default function SiteInformationPage({
  project,
  canManageInventory,
  sub,
  onSubChange,
  onReload,
  standalone = false,
}: {
  standalone?: boolean
  project: Project
  canManageInventory: boolean
  sub: SiteSubKey
  onSubChange: (key: string) => void
  onReload: () => void
}) {
  if (standalone) return sub === 'vehicles' ? <VehicleLifecyclePage project={project} onReload={onReload} />
    : sub === 'inventory' ? <InventoryPage projectId={project.id} canManage={canManageInventory} />
    : <SiteHandoverPage project={project} onReload={onReload} />
  return <div>
    <div className="section-heading-row">
      <div>
        <Typography.Title level={4}>现场信息</Typography.Title>
        <Typography.Text type="secondary">车辆、物品和甲方交接信息统一在项目范围内共享，便于现场人员接续工作</Typography.Text>
      </div>
    </div>
    <Tabs
      activeKey={sub}
      onChange={onSubChange}
      items={[
        { key: 'vehicles', label: <span><CarOutlined /> 现场车辆</span>, children: sub === 'vehicles' ? <VehicleLifecyclePage project={project} onReload={onReload} /> : null },
        { key: 'inventory', label: <span><InboxOutlined /> 物品与去向</span>, children: sub === 'inventory' ? <InventoryPage projectId={project.id} canManage={canManageInventory} /> : null },
        { key: 'handover', label: <span><ContactsOutlined /> 现场交接</span>, children: sub === 'handover' ? <SiteHandoverPage project={project} onReload={onReload} /> : null },
      ]}
    />
  </div>
}
