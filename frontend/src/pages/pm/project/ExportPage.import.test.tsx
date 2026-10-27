import { beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
const { post, navigate } = vi.hoisted(() => ({ post: vi.fn(), navigate: vi.fn() }))
vi.mock('../../../api/client', () => ({ api: { post, get: vi.fn() }, errMsg: () => 'error' }))
vi.mock('../../../stores/auth', () => ({ useAuth: () => ({ user: { role: 'pm' } }) }))
vi.mock('react-router-dom', () => ({ useNavigate: () => navigate }))
import ExportPage from './ExportPage'
const warning = '附件与审核状态不能作为新项目证据，交付项重新待提交'
const payload = { type: 'agvpm-project', project: { name: '副本' } }
async function chooseFile(container: HTMLElement) {
  fireEvent.click(screen.getByRole('button', { name: /高级：结构化快照与克隆/ }))
  const file = new File([JSON.stringify(payload)], 'project.json', { type: 'application/json' })
  Object.defineProperty(file, 'text', { value: async () => JSON.stringify(payload) })
  fireEvent.change(container.querySelector('input[type=file]')!, { target: { files: [file] } })
  await screen.findByText('JSON 导入预检')
}
beforeEach(() => { vi.clearAllMocks(); post.mockImplementation(async url => ({ data: url.endsWith('/preview') ? { valid: true, warnings: [warning], summary: { project: '副本' } } : { id: 'new-project', message: '已创建', warnings: [warning] } })) })
it('选择JSON只预检，展示证据重置提醒，取消不创建项目', async () => {
  const { container } = render(<ExportPage projectId="p1" />)
  await chooseFile(container)
  expect(screen.getByText(warning)).toBeInTheDocument()
  expect(post.mock.calls.map(([url]) => url)).toEqual(['/projects/import/preview'])
  fireEvent.click(screen.getByRole('button', { name: /取.*消/ }))
  expect(navigate).not.toHaveBeenCalled()
  expect(post).toHaveBeenCalledTimes(1)
})
it('重复确认只创建一次，失败后保留预检供重试', async () => {
  let reject: (error: Error) => void = () => {}
  post.mockImplementationOnce(async () => ({ data: { valid: true, warnings: [warning] } })).mockImplementationOnce(() => new Promise((_, r) => { reject = r }))
  const { container } = render(<ExportPage projectId="p1" />)
  await chooseFile(container)
  const button = screen.getByRole('button', { name: '确认创建项目' })
  fireEvent.click(button); fireEvent.click(button)
  await waitFor(() => expect(post).toHaveBeenCalledTimes(2))
  reject(new Error('offline'))
  await screen.findByText(/导入失败，预检内容已保留，可重试/)
  expect(screen.getByText(warning)).toBeInTheDocument()
  post.mockResolvedValueOnce({ data: { id: 'new-project', message: '已创建' } })
  await waitFor(() => expect(button).not.toHaveClass('ant-btn-loading'))
  fireEvent.click(button)
  await waitFor(() => expect(navigate).toHaveBeenCalledWith('/pm/projects/new-project'))
})
it('预检不通过时禁止创建', async () => {
  post.mockResolvedValueOnce({ data: { valid: false, errors: ['任务引用不存在'] } })
  const { container } = render(<ExportPage projectId="p1" />)
  await chooseFile(container)
  expect(screen.getByText('任务引用不存在')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '确认创建项目' })).toBeDisabled()
  expect(post).toHaveBeenCalledTimes(1)
})
