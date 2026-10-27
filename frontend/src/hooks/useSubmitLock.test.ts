import { describe, expect, it } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useSubmitLock } from './useSubmitLock'

describe('useSubmitLock 提交重入锁', () => {
  it('持锁期间再次获取返回 false（快速双击「确定」只放行一次）', () => {
    const { result } = renderHook(() => useSubmitLock())
    expect(result.current.tryAcquire()).toBe(true)
    // 第二次进入（如 confirmLoading 尚未把按钮置灰时的第二次点击）被挡下
    expect(result.current.tryAcquire()).toBe(false)
  })

  it('释放后可再次获取（提交失败后允许用户重试）', () => {
    const { result } = renderHook(() => useSubmitLock())
    expect(result.current.tryAcquire()).toBe(true)
    result.current.release()
    expect(result.current.tryAcquire()).toBe(true)
  })
})
