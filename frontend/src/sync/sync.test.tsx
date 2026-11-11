import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'

const { get, patch, post, remove, put, ids } = vi.hoisted(() => ({ get: vi.fn(), patch: vi.fn(), post: vi.fn(), remove: vi.fn(), put: vi.fn(), ids: { next: 0 } }))
vi.mock('../api/client', () => ({ api: { get, patch, post, delete: remove, put }, errMsg: () => '保存失败', newId: () => `new-${++ids.next}` }))
vi.mock('axios', () => ({ default: { isAxiosError: (error: { response?: unknown }) => !!error?.response } }))
import { listOps } from './rows'
import { useLive } from './useLive'

interface Item { id: string; name: string; arrived: boolean; arrived_by?: string | null; arrived_at?: string | null }
interface Snap { items: Item[] }
const snap = (): Snap => ({ items: [{ id: 'a', name: '充电桩', arrived: false }, { id: 'b', name: '围栏', arrived: false }] })
const answer = (data: unknown, etag: string) => ({ status: 200, data, headers: { etag } })

beforeEach(() => { vi.clearAllMocks(); document.body.innerHTML = ''; ids.next = 0 })

describe('自动同步', () => {
  it('asks again with the version in hand and keeps its copy on 304', async () => {
    get.mockResolvedValueOnce(answer(snap(), '"p-1"')).mockResolvedValueOnce({ status: 304, data: '', headers: {} })
    const { result } = renderHook(() => useLive<Snap>('/projects/p'))
    await waitFor(() => expect(result.current.data?.items).toHaveLength(2))
    const first = result.current.data
    await act(async () => { result.current.refresh(); await Promise.resolve() })
    expect(get.mock.calls[1][1].headers).toEqual({ 'If-None-Match': '"p-1"' })
    expect(result.current.data).toBe(first)
  })

  it('holds back a server copy fetched while a write is under way, then fetches a fresh one', async () => {
    get.mockResolvedValueOnce(answer(snap(), '"p-1"'))
    const { result } = renderHook(() => useLive<Snap>('/projects/p'))
    await waitFor(() => expect(result.current.data).not.toBeNull())
    let finishWrite: () => void = () => undefined
    const write = new Promise<void>((resolve) => { finishWrite = resolve })
    act(() => { result.current.mutate((data) => ({ items: data.items.map((item) => ({ ...item, arrived: true })) })); void result.current.track(write) })
    await act(async () => { result.current.refresh(); await Promise.resolve() })
    expect(get).toHaveBeenCalledTimes(1)  // nothing is fetched while the write is open
    get.mockResolvedValueOnce(answer({ items: [{ id: 'a', name: '充电桩', arrived: true }] }, '"p-2"'))
    await act(async () => { finishWrite(); await write })
    await waitFor(() => expect(result.current.data?.items).toHaveLength(1))
    expect(get).toHaveBeenCalledTimes(2)
  })

  it('reports that the server cannot be reached without dropping what is shown', async () => {
    get.mockResolvedValueOnce(answer(snap(), '"p-1"')).mockRejectedValueOnce(new Error('offline'))
    const { result } = renderHook(() => useLive<Snap>('/projects/p'))
    await waitFor(() => expect(result.current.data).not.toBeNull())
    await act(async () => { result.current.refresh(); await Promise.resolve() })
    await waitFor(() => expect(result.current.error).toBe('保存失败'))
    expect(result.current.data?.items).toHaveLength(2)
  })
})

describe('按格子保存', () => {
  const live = () => {
    let data = snap()
    const api = { data, error: '', refresh: vi.fn(), track: <R,>(write: Promise<R>) => write,
      mutate: (change: (current: Snap) => Snap) => { data = change(data); api.data = data } }
    return api
  }

  it('sends what the edit was based on, and a tick without it', async () => {
    const state = live()
    const ops = listOps<Snap, Item>(state, '/projects/p', 'items', 'items', { name: '名称' }, { arrived: 'arrived' }, 'me')
    patch.mockResolvedValue({ data: { id: 'a', name: '自动充电桩', arrived: false } })
    await ops.set(state.data.items[0], 'name', '自动充电桩', '充电桩')
    expect(patch).toHaveBeenCalledWith('/projects/p/items/a', { name: { from: '充电桩', to: '自动充电桩' } })
    patch.mockResolvedValue({ data: { id: 'a', name: '自动充电桩', arrived: true, arrived_by: 'me' } })
    const ticking = ops.set(state.data.items[0], 'arrived', true)
    expect(state.data.items[0]).toMatchObject({ arrived: true, arrived_by: 'me' })  // shown before the server answers
    await ticking
    expect(patch).toHaveBeenLastCalledWith('/projects/p/items/a', { arrived: { to: true } })
  })

  it('asks whose value stays when someone changed the same cell first', async () => {
    const state = live()
    const ops = listOps<Snap, Item>(state, '/projects/p', 'items', 'items', { name: '名称' }, {}, 'me')
    patch.mockRejectedValueOnce({ response: { status: 409, data: { conflicts: { name: { current: '快充桩', by: '李娜' } }, row: { id: 'a', name: '快充桩', arrived: false } } } })
      .mockResolvedValueOnce({ data: { id: 'a', name: '自动充电桩', arrived: false } })
    const saving = ops.set(state.data.items[0], 'name', '自动充电桩', '充电桩')
    await waitFor(() => expect(document.body.textContent).toContain('李娜刚把“名称”改成了：快充桩'))
    expect(state.data.items[0].name).toBe('快充桩')
    Array.from(document.querySelectorAll('button')).find((button) => button.textContent?.replace(/\s/g, '') === '用我的')!.click()
    await saving
    expect(patch).toHaveBeenLastCalledWith('/projects/p/items/a', { name: { from: '快充桩', to: '自动充电桩' } })
    expect(state.data.items[0].name).toBe('自动充电桩')
  })

  it('puts the old value back when saving fails', async () => {
    const state = live()
    const ops = listOps<Snap, Item>(state, '/projects/p', 'items', 'items')
    patch.mockRejectedValueOnce(new Error('offline'))
    await ops.set(state.data.items[0], 'name', '改不成')
    expect(state.data.items[0].name).toBe('充电桩')
  })

  it('adds with an id of its own, removes at once, and takes a failed add away again', async () => {
    const state = live()
    const ops = listOps<Snap, Item>(state, '/projects/p', 'items', 'items')
    post.mockResolvedValueOnce({ data: { id: 'new-1', name: '叉齿', arrived: false } })
    await ops.add({ name: '叉齿' })
    expect(post).toHaveBeenCalledWith('/projects/p/items', { id: 'new-1', name: '叉齿' })
    expect(state.data.items.map((item) => item.name)).toEqual(['充电桩', '围栏', '叉齿'])
    remove.mockResolvedValueOnce({ data: {} })
    await ops.remove(state.data.items[0])
    expect(remove).toHaveBeenCalledWith('/projects/p/items/a')
    expect(state.data.items.map((item) => item.id)).toEqual(['b', 'new-1'])
    post.mockRejectedValueOnce(new Error('offline'))
    await expect(ops.add({ name: '托盘' })).rejects.toThrow()
    expect(state.data.items).toHaveLength(2)
  })

  it('reorders the rows it is given and leaves every other row in its slot', async () => {
    const state = live()
    state.mutate(() => ({ items: [{ id: 'a', name: 'A', arrived: false }, { id: 'x', name: 'X', arrived: false }, { id: 'b', name: 'B', arrived: false }] }))
    const ops = listOps<Snap, Item>(state, '/projects/p', 'items', 'items')
    put.mockResolvedValueOnce({ data: {} })
    await ops.move([state.data.items[0], state.data.items[2]], state.data.items[2], -1)
    expect(put).toHaveBeenCalledWith('/projects/p/items/order', { ids: ['b', 'x', 'a'] })
    expect(state.data.items.map((item) => item.id)).toEqual(['b', 'x', 'a'])
  })
})
