import { beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import InventoryOverviewPage from './InventoryOverviewPage'
import { api } from '../../api/client'
vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn() }))
vi.mock('../../api/client', () => ({ api: { get: vi.fn() }, errMsg: () => '请求失败' }))
beforeEach(() => {
 vi.clearAllMocks()
 vi.mocked(api.get).mockImplementation(async url => ({ data: url === '/projects' ? [{ id: 'p1', name: '测试项目' }] : { items: [], total: 0, summary: { total_records: 9 } } }))
})
it('resets submitted search and every visible select together, retaining explicitly global summary scope', async () => {
 render(<InventoryOverviewPage />)
 const search = screen.getByPlaceholderText('搜索物品、编号、规格、位置或保管人')
 fireEvent.change(search, { target: { value: '工具箱' } }); fireEvent.keyDown(search, { key: 'Enter', code: 'Enter', charCode: 13, keyCode: 13 })
 for (const [label, option] of [['按项目筛选', '测试项目'], ['按归属筛选', '我方'], ['按分类筛选', '工具'], ['按状态筛选', '在现场']]) {
   fireEvent.mouseDown(screen.getByRole('combobox', { name: label }))
   fireEvent.click(await screen.findByText(option, { selector: '.ant-select-item-option-content' }))
 }
 await waitFor(() => expect(api.get).toHaveBeenLastCalledWith('/inventory', { params: { search: '工具箱', project_id: 'p1', ownership: 'company', category: 'tool', status: 'on_site', page: 1, page_size: 50 } }))
 expect(screen.getByText('以下汇总为全部可见项目，不随列表筛选变化')).toBeInTheDocument()
 fireEvent.click(screen.getByRole('button', { name: '清空筛选' }))
 await waitFor(() => expect(api.get).toHaveBeenLastCalledWith('/inventory', { params: { search: '', project_id: '', ownership: '', category: '', status: '', page: 1, page_size: 50 } }))
 expect(search).toHaveValue('')
 expect(document.querySelectorAll('.ant-select-selection-item')).toHaveLength(0)
 expect(screen.queryByRole('button', { name: '重置筛选' })).not.toBeInTheDocument()
})
it('also clears an unsubmitted search draft using reset', async () => {
 render(<InventoryOverviewPage />)
 const search = screen.getByPlaceholderText('搜索物品、编号、规格、位置或保管人')
 fireEvent.change(search, { target: { value: '草稿' } })
 fireEvent.click(screen.getByRole('button', { name: '重置筛选' }))
 expect(search).toHaveValue('')
})
