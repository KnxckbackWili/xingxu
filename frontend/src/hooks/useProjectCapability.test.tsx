import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { ProjectArchivedContext, ProjectCapabilitiesContext, ProjectStatusContext, useProjectCapability } from './useProjectCapability'

function Probe() {
  const edit = useProjectCapability('project.update', true)
  const plan = useProjectCapability('project.manage_plan', true)
  const exported = useProjectCapability('project.export', false)
  return <span>{JSON.stringify({ edit, plan, exported })}</span>
}
it('unknown state freezes project writes while authorized export remains available', () => {
  render(<ProjectArchivedContext.Provider value={false}><ProjectStatusContext.Provider value="legacy_unknown"><ProjectCapabilitiesContext.Provider value={['project.update', 'project.manage_plan', 'project.export']}><Probe /></ProjectCapabilitiesContext.Provider></ProjectStatusContext.Provider></ProjectArchivedContext.Provider>)
  expect(screen.getByText('{"edit":false,"plan":false,"exported":true}')).toBeInTheDocument()
})
it('unknown state never grants export permission to a member', () => {
  render(<ProjectStatusContext.Provider value="legacy_unknown"><ProjectCapabilitiesContext.Provider value={[]}><Probe /></ProjectCapabilitiesContext.Provider></ProjectStatusContext.Provider>)
  expect(screen.getByText('{"edit":false,"plan":false,"exported":false}')).toBeInTheDocument()
})
