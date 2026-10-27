import React from 'react'
import { Button, Result } from 'antd'

/** 全局错误边界：白屏变可见错误信息，方便定位。 */
export default class ErrorBoundary extends React.Component<{ children: React.ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  render() {
    if (this.state.error) {
      return (
        <Result
          status="error"
          title="页面出错了"
          subTitle={
            <div style={{ maxWidth: 600, margin: '0 auto' }}>
              <p style={{ wordBreak: 'break-all' }}>{String(this.state.error.message || this.state.error)}</p>
              <p style={{ color: '#999', fontSize: 12 }}>
                如果持续出现，请尝试清除浏览器缓存（Ctrl+Shift+R 强制刷新；或 DevTools → Application → Service Workers → Unregister）
              </p>
            </div>
          }
          extra={
            <Button type="primary" onClick={() => window.location.reload()}>
              重新加载
            </Button>
          }
        />
      )
    }
    return this.props.children
  }
}
