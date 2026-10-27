import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import type { UploadJob } from '../uploads/types'
const h = vi.hoisted(() => ({ list: vi.fn(), retry: vi.fn(), pause: vi.fn(), cancel: vi.fn(), removeCompleted: vi.fn(), observe: vi.fn(() => () => {}) }))
vi.mock('../uploads/queue', () => ({ uploadQueue: h, observeUploadQueue: h.observe, UPLOAD_QUEUE_EVENT: 'upload-test' }))
vi.mock('../api/client', () => ({ errMsg: (error: Error) => error.message }))
import UploadQueue from './UploadQueue'
const row = (patch: Partial<UploadJob> = {}): UploadJob => ({ key: 'a:id', owner_id: 'a', project_id: 'p', created_at: 1, updated_at: 1, intent: { client_uuid: 'id', filename: '现场证据.zip', size: 30, sha256: 'abc', content_type: '', document_ids: ['d'], note: '', entity_type: 'project', entity_id: '', category: '' }, file: null, durable_file: false, metadata_durable: true, last_modified: 1, session_id: 'session', chunk_hashes: [], phase: 'paused', hashed_bytes: 30, uploaded_bytes: 15, error: '', ...patch })
beforeEach(() => { vi.clearAllMocks(); h.list.mockResolvedValue([row()]) })
it('shows partial upload truthfully and warns before closing with an unpersisted file', async () => {
  render(<UploadQueue ownerId="a" />)
  fireEvent.click(screen.getByRole('button', { name: '打开上传队列' }))
  expect(await screen.findByText('现场证据.zip')).toBeVisible()
  expect(screen.getByText('原文件未保存到离线存储')).toBeVisible()
  expect(screen.queryByText('正式文件已保存')).toBeNull()
  const event = new Event('beforeunload', { cancelable: true })
  window.dispatchEvent(event)
  expect(event.defaultPrevented).toBe(true)
})
it('hides every original account row immediately when its owner prop changes', async () => {
  const view = render(<UploadQueue ownerId="a" />)
  fireEvent.click(screen.getByRole('button', { name: '打开上传队列' }))
  expect(await screen.findByText('现场证据.zip')).toBeVisible()
  view.rerender(<UploadQueue ownerId="b" />)
  expect(screen.queryByText('现场证据.zip')).toBeNull()
})
it('does not warn about closing after the formal result has been saved', async () => {
  h.list.mockResolvedValue([row({ phase: 'completed', uploaded_bytes: 30 })])
  render(<UploadQueue ownerId="a" />)
  fireEvent.click(screen.getByRole('button', { name: '打开上传队列' }))
  expect(await screen.findByText('正式文件已保存')).toBeVisible()
  expect(screen.queryByText('原文件未保存到离线存储')).toBeNull()
  const event = new Event('beforeunload', { cancelable: true })
  window.dispatchEvent(event)
  expect(event.defaultPrevented).toBe(false)
})
