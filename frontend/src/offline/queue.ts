/**
 * Offline queue for worker operations.
 *
 * C5-5: generalized to cover quantity reports, check items, deliverables and
 * issue submissions. Each op is typed; the backend `/worker/sync` dispatches
 * by type. Dedupe on the server is handled by client_uuid, so re-sending
 * after a crash is safe.
 *
 * C5-6: rejected items are moved to a separate "rejected" store (with the
 * server rejection reason) so they can be inspected, retried or deleted
 * instead of being stuck in the pending queue forever.
 *
 * HYPE-99: 队列按账号隔离。离线数据绑定到产生它的账号（setOfflineAccount），
 * 存储键带账号后缀——登出后切到别的账号，绝不会看到/重试/自动提交上一个
 * 账号的数据。登出（owner 置空）时队列不可读、自动同步不触发。
 *
 * 历史数据安全迁移：升级前的全局键（agvpm_offline_queue / agvpm_offline_rejected）
 * 无法确认归属账号，因此一律不迁移、不读取、不自动提交（也绝不删除），
 * 只在本地原样保留——宁可让旧数据留在浏览器里，也不冒把 A 的数据当 B 的提交的风险。
 */

/**
 * 升级前的全局键（归属无法确认）。运行时绝不读取/迁移/删除，
 * 仅导出供回归测试断言"旧数据原样保留、新逻辑不触碰"。
 */
export const LEGACY_QUEUE_KEY = 'agvpm_offline_queue'
export const LEGACY_REJECTED_KEY = 'agvpm_offline_rejected'
const OWNER_KEY = 'agvpm_offline_owner'

let _owner: string | null = null

// Only a verified login in this tab may bind an account. A shared-device login
// in another tab changes the cookies as well as OWNER_KEY; that must invalidate
// this tab's binding rather than silently relabel its queued work.
export function getOfflineAccount(): string | null {
  try {
    return _owner && localStorage.getItem(OWNER_KEY) === _owner ? _owner : null
  } catch {
    return _owner
  }
}

export const OFFLINE_ACCOUNT_EVENT = 'agvpm-offline-account'
export const OFFLINE_QUEUE_EVENT = 'agvpm-offline-queue'
let accountRevision = 0
export function getOfflineAccountRevision() { return accountRevision }

/** 绑定离线数据的归属账号。登录成功/fetchMe 后调用；登出时传 null。 */
export function setOfflineAccount(id: string | null) {
  _owner = id
  accountRevision++
  try {
    if (id) {
      localStorage.setItem(OWNER_KEY, id)
    } else {
      localStorage.removeItem(OWNER_KEY)
    }
  } catch {
    // localStorage 不可用（隐私模式等）：仅内存态生效
  }
  window.dispatchEvent(new Event(OFFLINE_ACCOUNT_EVENT))
}

function scopedKey(scope: 'queue' | 'rejected'): string | null {
  const owner = getOfflineAccount()
  return owner ? `agvpm_offline_${scope}:${owner}` : null
}

export type OfflineOpType = 'report' | 'checkitem' | 'deliverable' | 'issue' | 'field'

export interface QueuedReport {
  client_uuid: string
  payload: Record<string, unknown>
  queued_at: number
  type: OfflineOpType
}

export interface RejectedReport extends QueuedReport {
  reason: string
}

export function getQueue(): QueuedReport[] {
  const key = scopedKey('queue')
  if (!key) return []  // 未绑定账号（已登出）：不可读，杜绝跨账号自动提交
  try {
    const raw = localStorage.getItem(key)
    const arr = raw ? JSON.parse(raw) : []
    return (Array.isArray(arr) ? arr : []).map((i) => ({
      type: 'report', // 旧队列无 type 字段 → 视为数量填报
      ...i,
    }))
  } catch {
    return []
  }
}

export function enqueue(payload: Record<string, unknown>, type: OfflineOpType = 'report'): QueuedReport {
  const item: QueuedReport = {
    client_uuid: payload.client_uuid as string,
    payload,
    queued_at: Date.now(),
    type,
  }
  const key = scopedKey('queue')
  if (!key) return item  // 未绑定账号不入库（受保护页在登出后不可达，防御性兜底）
  const q = getQueue()
  q.push(item)
  localStorage.setItem(key, JSON.stringify(q))
  window.dispatchEvent(new Event(OFFLINE_QUEUE_EVENT))
  return item
}

export function removeFromQueue(uuids: string[]) {
  const key = scopedKey('queue')
  if (!key) return
  const q = getQueue().filter((i) => !uuids.includes(i.client_uuid))
  localStorage.setItem(key, JSON.stringify(q))
  window.dispatchEvent(new Event(OFFLINE_QUEUE_EVENT))
}

export function clearQueue() {
  const key = scopedKey('queue')
  if (key) localStorage.removeItem(key)
  window.dispatchEvent(new Event(OFFLINE_QUEUE_EVENT))
}

// ===== 被拒列表（C5-6）=====

export function getRejected(): RejectedReport[] {
  const key = scopedKey('rejected')
  if (!key) return []
  try {
    const raw = localStorage.getItem(key)
    const arr = raw ? JSON.parse(raw) : []
    return Array.isArray(arr) ? arr : []
  } catch {
    return []
  }
}

export function addRejected(item: QueuedReport, reason: string) {
  const key = scopedKey('rejected')
  if (!key) return
  const list = getRejected()
  if (!list.some((r) => r.client_uuid === item.client_uuid)) {
    list.push({ ...item, reason })
    localStorage.setItem(key, JSON.stringify(list))
  }
}

export function removeRejected(uuids: string[]) {
  const key = scopedKey('rejected')
  if (!key) return
  const list = getRejected().filter((i) => !uuids.includes(i.client_uuid))
  localStorage.setItem(key, JSON.stringify(list))
}

/** 重试：从被拒列表移回待同步队列（保留原 client_uuid 以幂等）。 */
export function retryRejected(uuid: string) {
  const key = scopedKey('rejected')
  if (!key) return
  const list = getRejected()
  const item = list.find((i) => i.client_uuid === uuid)
  if (!item) return
  const { reason: _reason, ...queued } = item
  const q = getQueue()
  if (!q.some(i => i.client_uuid === uuid)) q.push({ ...queued, queued_at: Date.now() })
  localStorage.setItem(scopedKey('queue')!, JSON.stringify(q))
  removeRejected([uuid])
}
