import { beforeEach, describe, expect, it } from 'vitest'
import {
  enqueue, getQueue, removeFromQueue, clearQueue,
  getRejected, addRejected, retryRejected,
  setOfflineAccount,
  LEGACY_QUEUE_KEY, LEGACY_REJECTED_KEY,
} from './queue'

/**
 * HYPE-99：离线队列按账号隔离。
 * - 队列/被拒列表绑定 owner（账号），不同账号互不可见、不可重试/提交；
 * - 登出（owner=null）后队列不可读，杜绝换号自动提交；
 * - 升级前遗留的全局键既不读取也不删除（归属无法确认，绝不自动提交）。
 */

beforeEach(() => {
  localStorage.clear()
  setOfflineAccount(null)
})

describe('离线队列按账号隔离（HYPE-99）', () => {
  it('A 账号的待同步记录只在 A 账号下可见', () => {
    setOfflineAccount('user-a')
    enqueue({ client_uuid: 'a-001', task_id: 't1' } as any, 'report')
    enqueue({ client_uuid: 'a-002', task_id: 't2' } as any, 'checkitem')
    expect(getQueue().map((i) => i.client_uuid)).toEqual(['a-001', 'a-002'])

    setOfflineAccount('user-b')
    expect(getQueue()).toEqual([])
  })

  it('切换账号不会让 A 的待同步数据被 B 提交', () => {
    setOfflineAccount('user-a')
    enqueue({ client_uuid: 'a-003' } as any, 'report')
    setOfflineAccount('user-b')
    // B 的同步（removeFromQueue）只能移除 B 自己的条目
    removeFromQueue(['a-003'])
    expect(getQueue()).toEqual([])

    // 回到 A：a-003 仍在，未被 B 误删/误提交
    setOfflineAccount('user-a')
    expect(getQueue().map((i) => i.client_uuid)).toEqual(['a-003'])
  })

  it('登出（owner=null）后队列不可读；同账号重登数据仍在', () => {
    setOfflineAccount('user-a')
    enqueue({ client_uuid: 'a-004' } as any, 'report')
    setOfflineAccount(null)
    expect(getQueue()).toEqual([])  // 登出即不可读，绝不自动提交

    // 该账号再次登录 → 队列恢复
    setOfflineAccount('user-a')
    expect(getQueue().map((i) => i.client_uuid)).toEqual(['a-004'])
  })

  it('被拒列表同样按账号隔离；retry 只回 A 的待同步队列', () => {
    setOfflineAccount('user-a')
    enqueue({ client_uuid: 'a-rj-01', type: 'report' } as any, 'report')
    addRejected(getQueue()[0], '服务端拒绝')
    removeFromQueue(['a-rj-01'])  // 与服务端拒绝流程一致：被拒条目从待同步队列移除
    expect(getQueue()).toEqual([])
    expect(getRejected().map((i) => i.client_uuid)).toEqual(['a-rj-01'])

    setOfflineAccount('user-b')
    expect(getRejected()).toEqual([])
    retryRejected('a-rj-01')
    expect(getQueue()).toEqual([])

    setOfflineAccount('user-a')
    expect(getQueue().map((i) => i.client_uuid)).toEqual([])  // 仍在被拒列表
    expect(getRejected().map((i) => i.client_uuid)).toEqual(['a-rj-01'])
    retryRejected('a-rj-01')
    expect(getQueue().map((i) => i.client_uuid)).toEqual(['a-rj-01'])
    expect(getRejected()).toEqual([])
  })

  it('clearQueue 只清当前账号的队列', () => {
    setOfflineAccount('user-a')
    enqueue({ client_uuid: 'a-005' } as any, 'report')
    setOfflineAccount('user-b')
    enqueue({ client_uuid: 'b-005' } as any, 'report')
    clearQueue()
    expect(getQueue()).toEqual([])
    setOfflineAccount('user-a')
    expect(getQueue().map((i) => i.client_uuid)).toEqual(['a-005'])
  })

  it('升级前遗留的全局队列键：不读取、不自动提交、不删除', () => {
    // 模拟旧版本写入的全局队列（无法确认归属账号）
    localStorage.setItem(LEGACY_QUEUE_KEY, JSON.stringify([{ client_uuid: 'legacy-1', payload: {} }]))
    localStorage.setItem(LEGACY_REJECTED_KEY, JSON.stringify([{ client_uuid: 'legacy-r1', reason: 'x' }]))

    setOfflineAccount('user-a')
    // 新队列读不到旧数据（绝不把归属不明的旧数据当 A 的提交）
    expect(getQueue()).toEqual([])
    expect(getRejected()).toEqual([])

    // 旧数据原样保留在浏览器里，未被删除
    expect(localStorage.getItem(LEGACY_QUEUE_KEY)).toContain('legacy-1')
    expect(localStorage.getItem(LEGACY_REJECTED_KEY)).toContain('legacy-r1')
  })
})
