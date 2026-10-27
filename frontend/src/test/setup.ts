import '@testing-library/jest-dom/vitest'
import { afterEach, vi } from 'vitest'
import { act, cleanup } from '@testing-library/react'
import { Modal, message } from 'antd'

// jsdom cases assert the notice contents, not wall-clock auto-dismiss. The current
// rc-notification can leave an auto-close timer alive after destroy when
// pauseOnHover=false; it may fire after Vitest removes window. Keep test notices
// open until the explicit cleanup below instead of leaking timers across teardown.
message.config({ duration: 0 })

// vitest 未开 globals，testing-library 的自动清理不会生效；
// 显式注册 afterEach(cleanup)，避免单个测试文件内用例之间 DOM 泄漏。
// antd 的 message/modal 使用挂在 body 上的静态容器，cleanup() 只卸载 React 树、不负责它们：
// 1) message.destroy()/Modal.destroyAll() 清空 antd 内部状态；
// 2) rc-motion 的 leave 动画在 jsdom 中永不完成（没有 transitionend），destroy 后旧 notice
//    的 DOM 仍带 leave 类留在容器里，文案依旧可被 query 命中。此时 React 已把这些节点从虚拟
//    DOM 移除，手动移除残留的 notice 层节点不会造成 reconciliation 冲突；容器本身保留，
//    下一次 message 调用会复用同一个容器，避免"渲染进已卸载容器"的问题。
afterEach(async () => {
  cleanup()
  await act(async () => {
    message.destroy()
    Modal.destroyAll()
  })
  document
    .querySelectorAll('.ant-message-notice-wrapper, .ant-notification-notice, .ant-modal-root')
    .forEach((node) => node.remove())
})

// antd v5 在 jsdom 下依赖 matchMedia / ResizeObserver / scrollTo
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
})

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal('ResizeObserver', ResizeObserverStub)

window.scrollTo = vi.fn() as any
