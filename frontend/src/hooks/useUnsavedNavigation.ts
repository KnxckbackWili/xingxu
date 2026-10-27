import { useCallback, useEffect, useRef, useState } from 'react'
import { Modal } from 'antd'
import { useBlocker } from 'react-router-dom'

/** One decision for links, programmatic navigation and Back/Forward. The ref is
 * updated synchronously so save-and-continue does not reopen a stale warning. */
export function useUnsavedNavigation({ title = '开工安排有未保存的修改', beforeConfirm }: { title?: string; beforeConfirm?: () => void } = {}) {
  const [dirty, updateDirty] = useState(false)
  const dirtyRef = useRef(false)
  const setDirty = useCallback((value: boolean) => {
    dirtyRef.current = value
    updateDirty(value)
  }, [])
  const blocker = useBlocker(({ currentLocation, nextLocation }) => dirtyRef.current && (
    currentLocation.pathname !== nextLocation.pathname || currentLocation.search !== nextLocation.search
  ))
  const currentBlocker = useRef(blocker)
  currentBlocker.current = blocker
  const deciding = useRef(false)
  const dialog = useRef<ReturnType<typeof Modal.confirm> | null>(null)

  useEffect(() => {
    if (blocker.state !== 'blocked') {
      dialog.current?.destroy(); dialog.current = null
      if (blocker.state === 'unblocked') deciding.current = false
      return
    }
    if (deciding.current) return
    if (!dirtyRef.current) {
      deciding.current = true
      blocker.proceed()
      return
    }
    if (dialog.current) return
    beforeConfirm?.()
    dialog.current = Modal.confirm({
      title,
      content: '继续填写会保留当前内容；放弃修改后将前往所选页面。',
      okText: '放弃修改并离开',
      cancelText: '继续填写',
      onOk: () => {
        if (deciding.current) return
        deciding.current = true
        setDirty(false)
        if (currentBlocker.current.state === 'blocked') currentBlocker.current.proceed()
      },
      onCancel: () => {
        if (deciding.current) return
        deciding.current = true
        if (currentBlocker.current.state === 'blocked') currentBlocker.current.reset()
      },
    })
  }, [blocker, dirty, setDirty, title, beforeConfirm])

  useEffect(() => {
    if (!dirty) return
    const prevent = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', prevent)
    return () => window.removeEventListener('beforeunload', prevent)
  }, [dirty])
  useEffect(() => () => { dialog.current?.destroy() }, [])
  return [dirty, setDirty] as const
}
