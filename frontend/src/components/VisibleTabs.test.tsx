import { useState } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import VisibleTabs from './VisibleTabs'
const items = [
  { key: 'info', label: '基本信息', children: <p>基本信息内容</p> },
  { key: 'disabled', label: '不可用功能', disabled: true, children: <p>不可用内容</p> },
  { key: 'tasks', label: '任务调整', children: <p>任务调整内容</p> },
  { key: 'members', label: '成员', children: <p>成员内容</p> },
]
function Controlled() {
  const [key, setKey] = useState('info')
  return <VisibleTabs items={items} activeKey={key} onChange={setKey} />
}
it('子菜单直接呈现，点击仍切换受控内容且正确关联面板', () => {
  render(<Controlled />)
  expect(screen.getAllByRole('tab')).toHaveLength(4)
  const members = screen.getByRole('tab', { name: '成员' })
  fireEvent.click(members)
  expect(members).toHaveAttribute('aria-selected', 'true')
  const panel = screen.getByRole('tabpanel', { name: '成员' })
  expect(panel.id).toBe(members.getAttribute('aria-controls'))
  expect(screen.getByText('成员内容')).toBeVisible()
})
it('键盘方向键跳过禁用项，Home/End 可到首末入口', () => {
  render(<Controlled />)
  const first = screen.getByRole('tab', { name: '基本信息' })
  first.focus()
  fireEvent.keyDown(first, { key: 'ArrowRight' })
  const task = screen.getByRole('tab', { name: '任务调整' })
  expect(task).toHaveFocus()
  expect(task).toHaveAttribute('aria-selected', 'true')
  fireEvent.keyDown(task, { key: 'End' })
  const last = screen.getByRole('tab', { name: '成员' })
  expect(last).toHaveFocus()
  fireEvent.keyDown(last, { key: 'Home' })
  expect(first).toHaveFocus()
})
it('同一页面多个标签组不共用面板 ID', () => {
  render(<><VisibleTabs items={items} /><VisibleTabs items={items} /></>)
  const ids = screen.getAllByRole('tab').map((tab) => tab.id)
  expect(new Set(ids).size).toBe(ids.length)
})
