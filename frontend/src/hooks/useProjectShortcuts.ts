import { useMemo, useSyncExternalStore } from 'react'
import { PROJECT_NAV_GROUPS } from '../constants/projectNav'

export const PROJECT_SHORTCUT_LIMIT = 50
const paths = new Map(PROJECT_NAV_GROUPS.flatMap(group => group.items.flatMap(item =>
  item.children ? item.children.map(child => [child.path, child.label] as const) : [[item.path, item.label] as const],
)))
export const shortcutSectionLabel = (section: string) => paths.get(section) ?? '概况'
export const shortcutSection = (section: string) => paths.has(section) ? section : 'overview'
export interface ProjectShortcuts {
  favorites: string[]
  recent: { id: string; section: string }[]
  temporary: boolean
}
const empty = (): ProjectShortcuts => ({ favorites: [], recent: [], temporary: false })
const validId = (id: unknown): id is string => typeof id === 'string' && /^[\w-]{1,128}$/.test(id)

function decode(raw: string | null): ProjectShortcuts {
  if (!raw) return empty()
  try {
    const data = JSON.parse(raw)
    const favorites = Array.isArray(data?.favorites) ? [...new Set(data.favorites.filter(validId))].slice(0, PROJECT_SHORTCUT_LIMIT) as string[] : []
    const seen = new Set<string>()
    const recent = (Array.isArray(data?.recent) ? data.recent : []).filter((item: unknown): item is { id: string; section: string } => {
      if (!item || typeof item !== 'object' || !('id' in item) || !validId(item.id) || seen.has(item.id)) return false
      seen.add(item.id)
      return true
    }).slice(0, 8).map((item: { id: string; section: string }) => ({ id: item.id, section: shortcutSection(item.section) }))
    return { favorites, recent, temporary: false }
  } catch { return empty() }
}

/** Only account-scoped IDs and known page segments are stored, never business text. */
export function createProjectShortcutStore(accountId: string | undefined, storage: () => Pick<Storage, 'getItem' | 'setItem'> = () => localStorage) {
  const key = accountId ? `agvpm.project-shortcuts.v1:${accountId}` : null
  let snapshot = empty()
  try { if (key) snapshot = decode(storage().getItem(key)) } catch { snapshot.temporary = true }
  const listeners = new Set<() => void>()
  const notify = () => listeners.forEach(listener => listener())
  const save = (next: ProjectShortcuts) => {
    if (!key) return
    snapshot = next
    try { storage().setItem(key, JSON.stringify({ favorites: next.favorites, recent: next.recent })); snapshot.temporary = false }
    catch { snapshot.temporary = true }
    notify()
  }
  const sync = (event: StorageEvent) => {
    if (key && (event.key === key || event.key === null)) { snapshot = decode(event.newValue); notify() }
  }
  return {
    getSnapshot: () => snapshot,
    subscribe: (listener: () => void) => {
      if (!listeners.size) window.addEventListener('storage', sync)
      listeners.add(listener)
      if (key && !snapshot.temporary) {
        try { const latest = decode(storage().getItem(key)); if (JSON.stringify(latest) !== JSON.stringify(snapshot)) { snapshot = latest; notify() } } catch { /* Keep usable in-memory preferences. */ }
      }
      return () => { listeners.delete(listener); if (!listeners.size) window.removeEventListener('storage', sync) }
    },
    toggleFavorite: (id: string) => {
      if (!key || !validId(id)) return false
      const exists = snapshot.favorites.includes(id)
      if (!exists && snapshot.favorites.length >= PROJECT_SHORTCUT_LIMIT) return false
      save({ ...snapshot, favorites: exists ? snapshot.favorites.filter(value => value !== id) : [...snapshot.favorites, id] })
      return true
    },
    visit: (id: string, section: string) => {
      if (!key || !validId(id)) return
      const normalized = shortcutSection(section)
      if (snapshot.recent[0]?.id === id && snapshot.recent[0]?.section === normalized) return
      save({ ...snapshot, recent: [{ id, section: normalized }, ...snapshot.recent.filter(item => item.id !== id)].slice(0, 8) })
    },
    clearRecent: () => save({ ...snapshot, recent: [] }),
  }
}

const stores = new Map<string | undefined, ReturnType<typeof createProjectShortcutStore>>()
export function useProjectShortcuts(accountId: string | undefined) {
  const store = useMemo(() => {
    if (!stores.has(accountId)) stores.set(accountId, createProjectShortcutStore(accountId))
    return stores.get(accountId)!
  }, [accountId])
  const state = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot)
  return { ...state, toggleFavorite: store.toggleFavorite, visit: store.visit, clearRecent: store.clearRecent }
}
