import axios from 'axios'
import { Modal, message } from 'antd'
import { createElement } from 'react'
import { api, errMsg, newId } from '../api/client'
import type { Conflict } from '../api/types'
import type { Live } from './useLive'

type Row = { id: string }

/** The editing operations of one list ("items" of a project, "rows" of a template…). */
export interface ListOps<R extends Row> {
  add: (values: Partial<R>) => Promise<void>
  set: (row: R, field: keyof R & string, to: unknown) => Promise<void>
  remove: (row: R) => Promise<void>
  move: (rows: R[], row: R, offset: number) => Promise<void>
  reorder: (ids: string[]) => Promise<void>
}

function show(value: unknown): string {
  if (value === null || value === undefined || value === '') return '（空）'
  if (typeof value === 'boolean') return value ? '是' : '否'
  return String(value)
}

/** Someone else changed the same cell first. Ask whose value stays. */
function askConflict(label: string, mine: unknown, conflict: Conflict): Promise<boolean> {
  return new Promise((resolve) => {
    Modal.confirm({
      title: '这一格刚被别人改过',
      content: createElement('div', null,
        createElement('p', null, `${conflict.by || '有人'}刚把${label ? `“${label}”` : '这里'}改成了：${show(conflict.current)}`),
        createElement('p', null, `你想改成：${show(mine)}`)),
      okText: '用我的', cancelText: '用对方的',
      onOk: () => resolve(true), onCancel: () => resolve(false),
    })
  })
}

/**
 * Operations on the list `key` of a live snapshot, saved to `${base}/${path}`.
 * Every change shows at once and is undone on the page if the server refuses it.
 */
export function listOps<S extends object, R extends Row>(live: Live<S>, base: string, path: string, key: keyof S & string,
  labels: Partial<Record<string, string>> = {}, stamps: Partial<Record<string, string>> = {}, me = ''): ListOps<R> {
  const rowsOf = (data: S) => data[key] as unknown as R[]
  const put = (change: (rows: R[]) => R[]) => live.mutate((data) => ({ ...data, [key]: change(rowsOf(data)) }))
  const replace = (row: R) => put((rows) => rows.map((item) => (item.id === row.id ? row : item)))

  const send = async (row: R, field: string, from: unknown, to: unknown, compare: boolean): Promise<void> => {
    try {
      const { data } = await api.patch(`${base}/${path}/${row.id}`, { [field]: compare ? { from, to } : { to } })
      replace(data as R)
    } catch (failure) {
      if (axios.isAxiosError(failure) && failure.response?.status === 409 && failure.response.data?.conflicts?.[field]) {
        const conflict = failure.response.data.conflicts[field] as Conflict
        replace(failure.response.data.row as R)
        if (await askConflict(labels[field] ?? '', to, conflict)) {
          put((rows) => rows.map((item) => (item.id === row.id ? { ...item, [field]: to } : item)))
          return send(row, field, conflict.current, to, true)
        }
        return
      }
      put((rows) => rows.map((item) => (item.id === row.id ? { ...item, [field]: from } : item)))
      message.error(errMsg(failure))
    }
  }

  const ops: ListOps<R> = {
    add: async (values) => {
      const id = newId()
      const draft = { id, created_at: new Date().toISOString(), created_by: me, updated_at: '', ...values } as unknown as R
      put((rows) => [...rows, draft])
      try {
        const { data } = await live.track(api.post(`${base}/${path}`, { id, ...values }))
        replace(data as R)
      } catch (failure) {
        put((rows) => rows.filter((item) => item.id !== id))
        message.error(errMsg(failure))
        throw failure
      }
    },
    set: (row, field, to) => {
      const from = (row as Record<string, unknown>)[field]
      if (from === to) return Promise.resolve()
      const stamp = stamps[field]
      const optimistic = { ...row, [field]: to, ...(stamp ? { [`${stamp}_by`]: to ? me : null, [`${stamp}_at`]: to ? new Date().toISOString() : null } : {}) }
      replace(optimistic as R)
      // A tick is "make it so": repeating it is harmless, so it carries no "from".
      return live.track(send(row, field, from, to, typeof to !== 'boolean'))
    },
    remove: async (row) => {
      put((rows) => rows.filter((item) => item.id !== row.id))
      try {
        await live.track(api.delete(`${base}/${path}/${row.id}`))
        const key = `deleted-${row.id}`
        message.open({
          key, type: 'success', duration: 6,
          content: createElement('span', null, '已删除　', createElement('a', {
            onClick: () => {
              message.destroy(key)
              void live.track(api.post(`${base}/${path}/${row.id}/restore`)).catch((failure) => message.error(errMsg(failure)))
            },
          }, '撤销')),
        })
      } catch (failure) {
        live.refresh()
        message.error(errMsg(failure))
      }
    },
    move: async (subset, row, offset) => {
      const index = subset.findIndex((item) => item.id === row.id)
      const target = index + offset
      if (index < 0 || target < 0 || target >= subset.length) return
      const moved = subset.map((item) => item.id)
      moved.splice(target, 0, moved.splice(index, 1)[0])
      await ops.reorder(moved)
    },
    reorder: async (subset) => {
      // The list may show only part of what is stored (one stage, one kind): the rows named
      // here trade places among themselves, every other row keeps its slot.
      const named = new Set(subset)
      let next = 0
      const ids = (live.data ? rowsOf(live.data) : []).map((item) => (named.has(item.id) ? subset[next++] : item.id))
      const position = new Map(ids.map((id, index) => [id, index]))
      put((rows) => [...rows].sort((a, b) => (position.get(a.id) ?? 1e9) - (position.get(b.id) ?? 1e9)))
      try {
        await live.track(api.put(`${base}/${path}/order`, { ids }))
      } catch (failure) {
        live.refresh()
        message.error(errMsg(failure))
      }
    },
  }
  return ops
}
