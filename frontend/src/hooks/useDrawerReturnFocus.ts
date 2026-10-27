import { useEffect, useRef, type MutableRefObject } from 'react'

/** Restore an intentional close after its own portal leaves, without stealing a new focus. */
export function useDrawerReturnFocus(open: boolean, requested: MutableRefObject<boolean>, portalClass: string, resolveTarget: () => HTMLElement | null) {
  const latestTarget = useRef(resolveTarget)
  latestTarget.current = resolveTarget
  useEffect(() => {
    if (open) { requested.current = false; return }
    if (!requested.current) return
    let frame = 0
    const expires = performance.now() + 1500
    const afterPortalClose = () => {
      if (document.querySelector(`.${portalClass} .ant-drawer-body`)) {
        if (performance.now() < expires) frame = requestAnimationFrame(afterPortalClose)
        else requested.current = false
        return
      }
      requested.current = false
      const target = latestTarget.current()
      const active = document.activeElement
      if (active instanceof HTMLElement && active !== document.body && active !== target
        && !active.closest(`.${portalClass}`) && active.matches('a, button, input, textarea, select, [contenteditable="true"]')) return
      if (target?.isConnected) target.focus()
    }
    frame = requestAnimationFrame(afterPortalClose)
    return () => cancelAnimationFrame(frame)
  }, [open, portalClass, requested])
}
