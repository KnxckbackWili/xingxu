import { useCallback, useRef } from 'react'

export interface SubmitLock {
  tryAcquire: () => boolean
  release: () => void
}

/**
 * 表单提交重入锁。
 *
 * 异步提交处理函数（如 Modal 的 onOk）必须在任何 await 之前同步调用
 * `tryAcquire()`：成功才继续，第二次进入直接返回 false。这样即使快速双击
 * 「确定」/ 点击后立即回车，在 `confirmLoading` 把按钮置灰之前也不会发出
 * 并发请求，从而避免同一个错误被重复弹多次（如重复的「服务器内部错误」
 * toast）。
 */
export function useSubmitLock(): SubmitLock {
  const lockedRef = useRef(false)
  const tryAcquire = useCallback(() => {
    if (lockedRef.current) return false
    lockedRef.current = true
    return true
  }, [])
  const release = useCallback(() => {
    lockedRef.current = false
  }, [])
  return { tryAcquire, release }
}
