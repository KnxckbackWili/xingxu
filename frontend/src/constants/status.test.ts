import { expect, it } from 'vitest'
import { isProjectStatus, isProjectWriteBlocked, projectStatusMeta } from './status'

it('only real states are states', () => {
  expect(isProjectStatus('constructor')).toBe(false)
})
it('known lifecycle labels and existing write policies are preserved', () => {
  expect(projectStatusMeta('preparing')).toMatchObject({ label: '准备', color: 'gold' })
  expect(projectStatusMeta('executing', true)).toMatchObject({ label: '已延期', baseLabel: '现场实施' })
  expect(isProjectWriteBlocked('archived')).toBe(true)
  expect(isProjectWriteBlocked('completed')).toBe(false)
  expect(isProjectWriteBlocked('suspended')).toBe(false)
  expect(isProjectWriteBlocked(undefined)).toBe(false)
})

it('retired project states cannot be selected for new writes', () => { for (const state of ['draft', 'planning', 'commissioning', 'pilot']) expect(isProjectStatus(state)).toBe(false) })
