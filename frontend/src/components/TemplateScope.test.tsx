import { useState } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import TemplateScope, { selectedWorkItems } from './TemplateScope'
const phases = [{ id: 'ph', name: '实施', modules: [{ id: 'old-module', name: '原模块', tasks: [{ id: 'w', name: '现场清点', quantity_type: 'manual' }] }] }, { id: 'prep', name: '项目准备', modules: [{ id: 'pm', tasks: [{ id: 'prepwork', name: '旧准备资料' }] }] }]
it('reads old module selection as source IDs, excludes retired preparation and writes work IDs', () => {
  expect(selectedWorkItems(phases, ['old-module', 'pm'])).toEqual(['w'])
  expect(selectedWorkItems(phases, ['old-module'], ['w'])).toEqual([])
})
it('keeps deselected work visible for reselection and has no quantity editor', () => {
  function View() { const [selected, set] = useState(['w']); return <TemplateScope phases={phases} selected={selected} onSelected={set} excluded={[]} onExcluded={() => {}} review showAll /> }
  render(<View />); const box = screen.getByRole('checkbox', { name: '现场清点' }); fireEvent.click(box)
  expect(screen.getByText('已选 0 项工作')).toBeVisible(); fireEvent.click(screen.getByRole('checkbox', { name: '现场清点' })); expect(screen.getByText('已选 1 项工作')).toBeVisible()
  expect(screen.queryByRole('spinbutton')).toBeNull(); expect(screen.queryByText('旧准备资料')).toBeNull(); expect(screen.getByText('原模块')).toBeVisible()
})
