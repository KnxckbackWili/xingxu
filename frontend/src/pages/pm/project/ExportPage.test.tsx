import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import dayjs from 'dayjs'

vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
}))

const apiGet = vi.fn()
const apiPost = vi.fn()
vi.mock('../../../stores/auth', () => ({ useAuth: () => ({ user: { role: 'admin' } }) }))
vi.mock('../../../api/client', () => ({
  api: { get: (...args: unknown[]) => apiGet(...args), post: (...args: unknown[]) => apiPost(...args) },
  errMsg: () => 'mock-error',
}))

import ExportPage from './ExportPage'

// 模块级保存原始 createElement（restoreAllMocks 后每次测试都从它恢复）
const origCreateElement = document.createElement.bind(document)

/** 捕获 <a download=...> 被设置的文件名。 */
function captureDownloadNames() {
  const names: string[] = []
  vi.spyOn(document, 'createElement').mockImplementation((tag: string, ...rest: any[]) => {
    const el = origCreateElement(tag as string, ...rest)
    if (tag === 'a') {
      let _download = ''
      Object.defineProperty(el, 'download', {
        get: () => _download,
        set: (v: string) => { _download = v; names.push(v) },
      })
      el.click = vi.fn()
    }
    return el
  })
  return names
}

/** 模拟 URL.createObjectURL（jsdom 不支持 blob URL）。 */
function mockObjectUrl() {
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock')
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
}

/**
 * HYPE-71：三个项目导出下载必须使用响应头里的文件名（安全化项目名_YYYY-MM-DD.ext），
 * 解析失败才回退到本地按项目名+当天日期拼接。断言 <a download> 的最终值。
 */
describe('ExportPage 下载文件名', () => {
  const today = dayjs().format('YYYY-MM-DD')

  beforeEach(() => {
    vi.clearAllMocks()
    mockObjectUrl()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('响应头有 filename* 时，优先使用响应头文件名（ZIP 入口）', async () => {
    const names = captureDownloadNames()
    apiGet.mockResolvedValue({
      data: new Blob(['x']),
      headers: {
        'content-disposition':
          `attachment; filename="project-export-${today}.zip"; filename*=UTF-8''%E5%8D%8E%E4%B8%9C_%E7%89%A9%E6%B5%81_AGV_%E4%BA%8C%E6%9C%9F_${today}.zip`,
      },
    })
    render(<ExportPage projectId="p1" projectName="华东/物流:AGV*二期" />)
    fireEvent.click(await screen.findByRole('button', { name: /导出项目包/ }))
    await waitFor(() => expect(names[0]).toBe(`华东_物流_AGV_二期_${today}.zip`))
  })

  it('响应头无 content-disposition 时，回退为安全化项目名_今天.ext（Excel 入口）', async () => {
    const names = captureDownloadNames()
    apiGet.mockResolvedValue({ data: new Blob(['x']), headers: {} })
    render(<ExportPage projectId="p1" projectName="华东/物流:AGV*二期" />)
    fireEvent.click(screen.getByRole('button', { name: /高级：结构化快照与克隆/ }))
    fireEvent.click(await screen.findByRole('button', { name: /导出 Excel/ }))
    await waitFor(() => expect(names[0]).toBe(`华东_物流_AGV_二期_${today}.xlsx`))
  })

  it('项目名安全化后为空（如全非法字符）时，回退为「项目_今天.ext」（JSON 入口）', async () => {
    const names = captureDownloadNames()
    apiGet.mockResolvedValue({ data: new Blob(['x']), headers: {} })
    render(<ExportPage projectId="p1" projectName="..." />)
    fireEvent.click(screen.getByRole('button', { name: /高级：结构化快照与克隆/ }))
    fireEvent.click(await screen.findByRole('button', { name: /导出 JSON 快照/ }))
    await waitFor(() => expect(names[0]).toBe(`项目_${today}.json`))
  })
})

it('allows explicit draft preflight for an active-project backup without changing the original file', async () => {
  const original = { type: 'agvpm-project', project: { name: '现场项目', status: 'executing' }, modules: [] }
  apiPost.mockResolvedValueOnce({ data: { valid: false, summary: { project: '现场项目' }, errors: ['不能直接实施'] } })
    .mockResolvedValueOnce({ data: { valid: true, summary: { project: '现场项目' }, warnings: [] } })
  const { container } = render(<ExportPage projectId="p1" />)
  fireEvent.click(screen.getByRole('button', { name: /高级：结构化快照与克隆/ }))
  const file = new File(['fixture'], 'project.json', { type: 'application/json' })
  Object.defineProperty(file, 'text', { value: async () => JSON.stringify(original) })
  fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [file] } })
  fireEvent.click(await screen.findByRole('button', { name: '按筹备重新预检' }))
  await screen.findByText(/新项目将从筹备开始/)
  expect(apiPost).toHaveBeenLastCalledWith('/projects/import/preview', { ...original, project: { ...original.project, status: 'preparing' } })
  expect(original.project.status).toBe('executing')
  expect(screen.getByText('确认创建项目').closest('button')).toBeEnabled()
})
