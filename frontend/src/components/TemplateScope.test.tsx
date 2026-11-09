import { useState } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import TemplateScope, { selectedWorkItems } from './TemplateScope'
const phases = [{ id: 'ph', name: '实施', work_items: [{ id: 'w', name: '现场清点', kind: 'other', group_label: '现场分组' }] }]
it('selects work IDs and honours exclusions', () => {
  expect(selectedWorkItems(phases, ['w', 'unknown'])).toEqual(['w'])
  expect(selectedWorkItems(phases, ['w'], ['w'])).toEqual([])
})
it('keeps deselected work visible for reselection and has no quantity editor', () => {
  function View() { const [selected, set] = useState(['w']); return <TemplateScope phases={phases} selected={selected} onSelected={set} excluded={[]} onExcluded={() => {}} review showAll /> }
  render(<View />); const box = screen.getByRole('checkbox', { name: '现场清点' }); fireEvent.click(box)
  expect(screen.getByText('已选 0 项工作')).toBeVisible(); fireEvent.click(screen.getByRole('checkbox', { name: '现场清点' })); expect(screen.getByText('已选 1 项工作')).toBeVisible()
  expect(screen.queryByRole('spinbutton')).toBeNull(); expect(screen.getByText('现场分组')).toBeVisible()
})
