import { render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import StartupPage from './StartupPage'
import type { Project } from '../../../api'
it.each(['work','people','schedule','entry'])('old %s bookmarks resolve to the overview setup',step=>{
  const project={id:'p1'} as Project
  render(<MemoryRouter initialEntries={[`/pm/projects/p1/start?step=${step}`]}><Routes>
    <Route path="/pm/projects/p1/start" element={<StartupPage project={project} canEdit onReload={vi.fn()} />} />
    <Route path="/pm/projects/p1/overview" element={<div>概况筹备清单</div>} />
  </Routes></MemoryRouter>)
  expect(screen.getByText('概况筹备清单')).toBeVisible()
  expect(screen.queryByText('开工向导')).not.toBeInTheDocument()
})
