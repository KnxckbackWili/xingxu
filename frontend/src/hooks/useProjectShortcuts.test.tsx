import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { createProjectShortcutStore, useProjectShortcuts } from './useProjectShortcuts'

const storage = () => {
  const values = new Map<string, string>()
  return { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key, value) }, values }
}

describe('personal project shortcuts', () => {
  it('persists only IDs and safe page segments, deduplicates visits and bounds history', () => {
    const disk = storage(), store = createProjectShortcutStore('pm', () => disk)
    store.toggleFavorite('project-1')
    for (let i = 0; i < 12; i++) store.visit(`project-${i}`, 'schedule')
    store.visit('project-10', 'files')
    store.visit('project-10', 'https://example.com/private?token=secret')
    expect(store.getSnapshot().recent).toHaveLength(8)
    expect(store.getSnapshot().recent[0]).toEqual({ id: 'project-10', section: 'overview' })
    expect(store.getSnapshot().recent.filter(item => item.id === 'project-10')).toHaveLength(1)
    expect(createProjectShortcutStore('pm', () => disk).getSnapshot()).toEqual(store.getSnapshot())
    expect(disk.values.get('agvpm.project-shortcuts.v1:pm')).not.toMatch(/secret|temporary|https/)
    expect(createProjectShortcutStore('worker', () => disk).getSnapshot().favorites).toEqual([])
  })
  it('limits favorites without losing any and permits cancellation after reaching the limit', () => {
    const disk = storage(), store = createProjectShortcutStore('limit', () => disk)
    for (let i = 0; i < 50; i++) expect(store.toggleFavorite(`p-${i}`)).toBe(true)
    expect(store.toggleFavorite('overflow')).toBe(false)
    expect(store.getSnapshot().favorites).toHaveLength(50)
    expect(store.toggleFavorite('p-0')).toBe(true)
    expect(store.toggleFavorite('replacement')).toBe(true)
  })
  it('handles corrupted data and never accepts arbitrary paths or IDs', () => {
    const disk = storage()
    disk.setItem('agvpm.project-shortcuts.v1:bad', '{broken')
    expect(createProjectShortcutStore('bad', () => disk).getSnapshot().recent).toEqual([])
    disk.setItem('agvpm.project-shortcuts.v1:bad', JSON.stringify({ favorites: ['p', 'p', null, '../escape'], recent: [{ id: 'p', section: '../admin' }, null, { id: 'p', section: 'schedule' }, { id: 'q', section: { href: 'evil' } }] }))
    const store = createProjectShortcutStore('bad', () => disk)
    expect(store.getSnapshot().favorites).toEqual(['p'])
    expect(store.getSnapshot().recent).toEqual([{ id: 'p', section: 'overview' }, { id: 'q', section: 'overview' }])
    expect(store.toggleFavorite('../escape')).toBe(false)
  })
  it('keeps in-memory preferences usable when browser storage is blocked', () => {
    const store = createProjectShortcutStore('blocked', () => { throw new Error('storage blocked') })
    const listener = vi.fn(), unsubscribe = store.subscribe(listener)
    store.toggleFavorite('p'); store.visit('p', 'plan')
    expect(store.getSnapshot()).toEqual({ favorites: ['p'], recent: [{ id: 'p', section: 'plan' }], temporary: true })
    expect(listener).toHaveBeenCalledTimes(2)
    store.clearRecent()
    expect(store.getSnapshot().favorites).toEqual(['p'])
    expect(store.getSnapshot().recent).toEqual([])
    unsubscribe()
  })
  it('does not create anonymous preferences or expose the previous account during a switch', () => {
    const { result, rerender } = renderHook(({ id }) => useProjectShortcuts(id), { initialProps: { id: 'shortcut-hook-a' as string | undefined } })
    act(() => { result.current.toggleFavorite('p-a'); result.current.visit('p-a', 'plan') })
    rerender({ id: 'shortcut-hook-b' })
    expect(result.current.favorites).toEqual([])
    expect(result.current.recent).toEqual([])
    act(() => { result.current.toggleFavorite('p-b') })
    rerender({ id: 'shortcut-hook-a' })
    expect(result.current.favorites).toEqual(['p-a'])
    rerender({ id: undefined })
    act(() => { result.current.toggleFavorite('anonymous') })
    expect(result.current.favorites).toEqual([])
  })
  it('handles other-tab changes and detaches the event listener after unmount', () => {
    const disk = storage(), store = createProjectShortcutStore('cross-tab', () => disk)
    const listener = vi.fn(), unsubscribe = store.subscribe(listener)
    window.dispatchEvent(new StorageEvent('storage', { key: 'agvpm.project-shortcuts.v1:another', newValue: '{"favorites":["other"]}' }))
    expect(listener).not.toHaveBeenCalled()
    window.dispatchEvent(new StorageEvent('storage', { key: 'agvpm.project-shortcuts.v1:cross-tab', newValue: '{"favorites":["p"]}' }))
    expect(store.getSnapshot().favorites).toEqual(['p'])
    unsubscribe()
    window.dispatchEvent(new StorageEvent('storage', { key: null, newValue: null }))
    expect(listener).toHaveBeenCalledTimes(1)
  })
})
