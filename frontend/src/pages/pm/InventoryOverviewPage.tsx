import { WorkPageHeader, WorkSection } from '../../components/WorkPage'
import { NAV_LABEL, NAV_DESCRIPTION } from '../../constants/nav'
import './SettingsPages.css'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Card, Empty, Input, Pagination, Select, Space, Spin, Table, Tag } from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api } from '../../api/client'
import { useMediaQuery } from '../../hooks/useMediaQuery'
import { MEDIA_QUERY } from '../../constants/breakpoints'

const OWNER: Record<string, { label: string; color: string }> = {
  company: { label: '我方', color: 'blue' }, client: { label: '甲方', color: 'gold' }, third_party: { label: '第三方', color: 'default' },
}
const CATEGORY: Record<string, string> = { equipment: '设备', tool: '工具', spare_part: '备件', material: '材料', consumable: '耗材', document: '资料', other: '其他' }
const STATUS: Record<string, string> = { expected: '待到场', in_transit: '运输中', on_site: '在现场', in_use: '使用中', loaned: '借出', consumed: '已耗尽', returned: '已归还', lost: '遗失', damaged: '损坏', scrapped: '报废' }

export default function InventoryOverviewPage() {
  const navigate = useNavigate()
  const isMobile = useMediaQuery(MEDIA_QUERY.mobile)
  const loadSequence = useRef(0)
  const [loadError, setLoadError] = useState(false)
  const [data, setData] = useState<any>({ items: [], summary: {}, total: 0 })
  const [projects, setProjects] = useState<any[]>([])
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [searchInput, setSearchInput] = useState('')
  const [filters, setFilters] = useState({ search: '', project_id: '', ownership: '', category: '', status: '' })
  const load = async (nextPage = page) => {
    const request = ++loadSequence.current
    setLoading(true); setLoadError(false)
    try { const result = await api.get('/inventory', { params: { ...filters, page: nextPage, page_size: 50 } }); if (request === loadSequence.current) setData(result.data) }
    catch { if (request === loadSequence.current) setLoadError(true) } finally { if (request === loadSequence.current) setLoading(false) }
  }
  useEffect(() => { api.get('/projects').then((response) => setProjects(response.data)).catch(() => {}) }, [])
  useEffect(() => { setPage(1); void load(1); return () => { loadSequence.current++ } }, [filters])
  const columns = useMemo(() => [
    { title: '项目', dataIndex: 'project_name', width: 220, render: (value: string, row: any) => <button className="inventory-project-link" onClick={() => navigate(`/pm/projects/${row.project_id}/inventory`)}>{value}</button> },
    { title: '物品', key: 'name', width: 250, render: (_: any, row: any) => <div className="inventory-name"><strong>{row.name}</strong><span>{[row.item_code, row.specification, row.serial_number].filter(Boolean).join(' · ') || '未填写编号和规格'}</span></div> },
    { title: '归属', dataIndex: 'ownership', width: 80, render: (value: string) => <Tag color={OWNER[value]?.color}>{OWNER[value]?.label}</Tag> },
    { title: '分类', dataIndex: 'category', width: 80, render: (value: string) => CATEGORY[value] ?? value },
    { title: '数量', key: 'quantity', width: 100, render: (_: any, row: any) => <span className={row.low_stock ? 'inventory-low' : ''}>{row.quantity} {row.unit}</span> },
    { title: '状态', dataIndex: 'status', width: 90, render: (value: string) => STATUS[value] ?? value },
    { title: '位置', dataIndex: 'location', width: 160, render: (value: string) => value || '-' },
    { title: '保管人', dataIndex: 'custodian', width: 120, render: (value: string) => value || '-' },
  ], [navigate])
  const stats = [['物品记录', data.summary.total_records ?? 0], ['覆盖项目', data.summary.project_count ?? 0], ['我方物品', data.summary.company_records ?? 0], ['甲方物品', data.summary.client_records ?? 0], ['需要关注', data.summary.attention_records ?? 0]]
  const hasFilters = Object.values(filters).some(Boolean)
  const clearFilters = () => { setSearchInput(''); setFilters({ search: '', project_id: '', ownership: '', category: '', status: '' }) }
  const emptyNode = hasFilters
    ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前筛选范围没有物品"><Button className="touch-target" onClick={clearFilters}>清空筛选</Button></Empty>
    : <Empty image={<InboxOutlined style={{ fontSize: 42, color: '#b6c2be' }} />} description="暂无物品记录。打开项目，在“现场 → 物品”中登记" />
  const paginationProps = { current: page, pageSize: 50, total: data.total, showSizeChanger: false, showTotal: (value: number) => `共 ${value} 条`, onChange: (next: number) => { setPage(next); void load(next) } }
  return <div className="settings-work-page inventory-page inventory-overview-page">
    <WorkPageHeader title={NAV_LABEL['/pm/inventory']} description={NAV_DESCRIPTION['/pm/inventory']}
      primary={<Button type="primary" onClick={() => navigate('/pm/projects')}>打开项目</Button>}
      tools={<Button onClick={() => void load()} loading={loading}>刷新</Button>}
      meta={`全部可见项目 · ${data.summary.total_records ?? 0} 条物品记录 · ${data.summary.attention_records ?? 0} 条需要关注`} />
    <WorkSection title="查找物品" description="在对应项目中查看流水、修改数量或登记去向。" filters={
    <div className="inventory-filters inventory-global-filters">
      <Input.Search value={searchInput} onChange={(event) => setSearchInput(event.target.value)} allowClear placeholder="搜索物品、编号、规格、位置或保管人" onSearch={(search) => setFilters((old) => ({ ...old, search }))} />
      <Select allowClear showSearch optionFilterProp="label" placeholder="选择项目" aria-label="按项目筛选" value={filters.project_id || undefined} onChange={(project_id = '') => setFilters((old) => ({ ...old, project_id }))} options={projects.map((project) => ({ value: project.id, label: project.name }))} />
      <Select allowClear placeholder="归属" aria-label="按归属筛选" value={filters.ownership || undefined} onChange={(ownership = '') => setFilters((old) => ({ ...old, ownership }))} options={Object.entries(OWNER).map(([value, meta]) => ({ value, label: meta.label }))} />
      <Select allowClear placeholder="分类" aria-label="按分类筛选" value={filters.category || undefined} onChange={(category = '') => setFilters((old) => ({ ...old, category }))} options={Object.entries(CATEGORY).map(([value, label]) => ({ value, label }))} />
      <Select allowClear placeholder="状态" aria-label="按状态筛选" value={filters.status || undefined} onChange={(status = '') => setFilters((old) => ({ ...old, status }))} options={Object.entries(STATUS).map(([value, label]) => ({ value, label }))} />
      {(hasFilters || searchInput) && <Button onClick={clearFilters}>重置筛选</Button>}
    </div>}>
    {loadError ? <Alert type="error" showIcon message="物品总览加载失败" action={<Button onClick={() => load()}>重试</Button>} /> : isMobile ? (
      loading ? <div className="work-empty"><Spin /></div> : data.items.length === 0 ? emptyNode : (
        <>
          <div className="mobile-card-list">
            {data.items.map((row: any) => (
              <Card key={row.id} size="small">
                <Space direction="vertical" size={6} style={{ width: '100%' }}>
                  <div className="mobile-card-title">{row.name}</div>
                  <div className="mobile-card-row">
                    <span className="mobile-card-value" style={{ color: 'var(--agv-text-secondary)' }}>
                      {[row.item_code, row.specification, row.serial_number].filter(Boolean).join(' · ') || '未填写编号和规格'}
                    </span>
                  </div>
                  <div className="mobile-card-row">
                    <Tag color={OWNER[row.ownership]?.color}>{OWNER[row.ownership]?.label ?? row.ownership}</Tag>
                    <Tag>{CATEGORY[row.category] ?? row.category}</Tag>
                    <Tag>{STATUS[row.status] ?? row.status}</Tag>
                    {row.low_stock && <Tag color="red">库存告急</Tag>}
                  </div>
                  <div className="mobile-card-row">
                    <span className="mobile-card-label">项目</span>
                    <span className="mobile-card-value"><button className="inventory-project-link" onClick={() => navigate(`/pm/projects/${row.project_id}/inventory`)}>{row.project_name}</button></span>
                  </div>
                  <div className="mobile-card-row">
                    <span className="mobile-card-label">数量</span>
                    <span className="mobile-card-value"><span className={row.low_stock ? 'inventory-low' : ''}>{row.quantity} {row.unit}</span></span>
                    <span className="mobile-card-label">位置</span>
                    <span className="mobile-card-value">{row.location || '-'}</span>
                    <span className="mobile-card-label">保管人</span>
                    <span className="mobile-card-value">{row.custodian || '-'}</span>
                  </div>
                </Space>
              </Card>
            ))}
          </div>
          {data.total > 50 && (
            <div style={{ marginTop: 12, textAlign: 'right' }}><Pagination {...paginationProps} size="small" /></div>
          )}
        </>
      )
    ) : (
      <Table rowKey="id" columns={columns} dataSource={data.items} loading={loading} scroll={{ x: 1100 }} pagination={paginationProps} locale={{ emptyText: emptyNode }} />
    )}
    </WorkSection>
    <details className="work-detail-summary settings-detail">
      <summary>全部项目汇总</summary>
      <p className="work-helper">以下汇总为全部可见项目，不随列表筛选变化</p>
      <div className="inventory-stats inventory-stats-global">{stats.map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}</div>
    </details>
  </div>
}
