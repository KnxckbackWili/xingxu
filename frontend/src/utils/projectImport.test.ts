import { expect, it } from 'vitest'
import { draftProjectImport, projectImportSourceStatus } from './projectImport'

it('copies only project status while retaining the source and all nested plan details', () => {
  const project = Object.freeze({ name: '历史方案', status: 'legacy-live', start_date: '2026-10-05' })
  const modules = [{ tasks: [{ name: '路线', target_quantity: 25, unit: '米' }] }]
  const original = Object.freeze({ type: 'agvpm-project', project, modules })
  expect(draftProjectImport(original)).toEqual({ sourceStatus: 'legacy-live', payload: { ...original, project: { ...project, status: 'preparing' } } })
  expect(original.project.status).toBe('legacy-live')
  expect(draftProjectImport(original)?.payload.modules).toBe(modules)
})

it('leaves initial states and malformed project shapes for the regular backend preflight', () => {
  for (const status of ['preparing']) expect(draftProjectImport({ project: { status } })).toBeNull()
  for (const payload of [null, [], { project: [] }, { project: 'executing' }, { project: { status: 42 } }, { project: {} }]) {
    expect(draftProjectImport(payload)).toBeNull()
    expect(projectImportSourceStatus(payload)).toBeUndefined()
  }
})
