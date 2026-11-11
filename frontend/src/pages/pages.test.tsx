import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import type { Snapshot } from '../api/types'

const { get, navigate } = vi.hoisted(() => ({ get: vi.fn(), navigate: vi.fn() }))
vi.mock('../api/client', () => ({ api: { get, post: vi.fn(), patch: vi.fn() }, errMsg: () => '读取失败', newId: () => 'id', isAuthed: () => false }))
vi.mock('react-router-dom', () => ({ useNavigate: () => navigate, Link: ({ children }: { children: unknown }) => children, useLocation: () => ({ search: '' }) }))
import Home from './Home'
import { safeNext } from './Login'
import { gapCounts } from './project/context'

const gaps = { vehicles: { total: 6, missing: [{ id: 'v', name: 'QF-003', fleet_no: '3', missing: ['调试', '交付'] }] }, work: [{ id: 'w', stage: '现场实施', name: '建图' }],
  issues: [], documents: [{ id: 'd', name: '验收单' }, { id: 'e', name: '施工方案' }], items: [] }
const project = (extra: object) => ({ id: 'p1', name: '苏州工厂', contract_no: 'HT-1', customer: '某客户', note: '', is_closed: false, rev: 1, created_at: '', updated_at: '', deleted_at: null, gaps, ...extra })

beforeEach(() => { vi.clearAllMocks() })

describe('首页缺口总览', () => {
  const show = async (projects: object[]) => {
    get.mockResolvedValue({ status: 200, data: { projects }, headers: { etag: '"1"' } })
    render(<Home />)
    return within(await screen.findByRole('table', { name: '进行中的项目' }))
  }

  it('shows what each project lacks and "齐了" where nothing is missing', async () => {
    const table = await show([project({})])
    expect(table.getByRole('button', { name: /还差 1 台/ })).toHaveTextContent('5 / 6 台做完')
    expect(table.getByRole('button', { name: '1 项没做' })).toBeInTheDocument()
    expect(table.getByRole('button', { name: '缺 2 份' })).toBeInTheDocument()
    expect(table.getAllByRole('button', { name: '齐了' })).toHaveLength(2)
  })

  it('a number leads to that tab showing only what is left; "齐了" leads to the whole tab', async () => {
    const table = await show([project({})])
    fireEvent.click(table.getByRole('button', { name: '缺 2 份' }))
    expect(navigate).toHaveBeenCalledWith('/projects/p1/documents?todo=1')
    fireEvent.click(table.getAllByRole('button', { name: '齐了' })[0])
    expect(navigate).toHaveBeenLastCalledWith('/projects/p1/issues')
  })

  it('lists every gap by name when a project is opened', async () => {
    await show([project({})])
    expect(screen.queryByText('QF-003（3 号）：调试、交付')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '展开 苏州工厂 的缺口明细' }))
    expect(screen.getByText('QF-003（3 号）：调试、交付')).toBeInTheDocument()
    expect(screen.getByText('现场实施 · 建图')).toBeInTheDocument()
    expect(screen.getByText('验收单')).toBeInTheDocument()
  })

  it('keeps finished projects out of the table and offers a first project when there is none', async () => {
    get.mockResolvedValue({ status: 200, data: { projects: [project({ id: 'p2', name: '老项目', is_closed: true, gaps: null })] }, headers: {} })
    render(<Home />)
    expect(await screen.findByText('还没有进行中的项目。')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /已结束的项目 1/ }))
    expect(screen.getByText('老项目')).toBeInTheDocument()
  })

  it('says so when the server cannot be reached', async () => {
    get.mockRejectedValue(new Error('offline'))
    render(<Home />)
    await waitFor(() => expect(screen.getByText('读不到项目')).toBeInTheDocument())
  })
})

describe('五条“缺”的规则', () => {
  it('counts the same way the server does', () => {
    const row = { created_at: '', created_by: null, updated_at: '' }
    const snap = {
      steps: [{ id: 's1', name: '到货', ...row }, { id: 's2', name: '交付', ...row }],
      vehicles: [{ id: 'v1', ...row }, { id: 'v2', ...row }, { id: 'v3', ...row }],
      marks: [{ vehicle_id: 'v1', step_id: 's1' }, { vehicle_id: 'v1', step_id: 's2' }, { vehicle_id: 'v2', step_id: 's1' }],
      work: [{ id: 'w1', done: true }, { id: 'w2', done: false }],
      issues: [{ id: 'i1', is_closed: false }, { id: 'i2', is_closed: true }, { id: 'i3', is_closed: false }],
      documents: [{ id: 'd1' }, { id: 'd2' }],
      files: [{ owner_kind: 'document', owner_id: 'd1' }, { owner_kind: 'issue', owner_id: 'd2' }, { owner_kind: 'other', owner_id: null }],
      items: [{ id: 'm1', arrived: true }],
    } as unknown as Snapshot
    expect(gapCounts(snap)).toEqual({ vehicles: 2, work: 1, issues: 2, documents: 1, items: 0 })
    expect(gapCounts({ ...snap, steps: [] }).vehicles).toBe(0)
  })
})

describe('登录后的去向', () => {
  it('only ever returns a path inside the app', () => {
    expect(safeNext('?next=%2Fprojects%2Fp1%2Fissues%3Ftodo%3D1')).toBe('/projects/p1/issues?todo=1')
    for (const bad of ['?next=https%3A%2F%2Fevil.example', '?next=%2F%2Fevil.example', '?next=%2Flogin%3Fnext%3D%2Flogin', '', '?next=javascript%3Aalert(1)']) expect(safeNext(bad)).toBe('/')
  })
})
