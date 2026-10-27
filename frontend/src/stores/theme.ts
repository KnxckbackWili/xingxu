import { create } from 'zustand'

export type ThemeMode = 'light' | 'dark'

const THEME_KEY = 'agvpm_theme_mode'

function initialMode(): ThemeMode {
  try {
    const stored = localStorage.getItem(THEME_KEY)
    if (stored === 'dark' || stored === 'light') return stored
    return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  } catch {
    return 'light'
  }
}

interface ThemeState {
  mode: ThemeMode
  setMode: (mode: ThemeMode) => void
  toggle: () => void
}

export const useThemeStore = create<ThemeState>((set, get) => ({
  mode: initialMode(),
  setMode: (mode) => {
    try { localStorage.setItem(THEME_KEY, mode) } catch { /* ignore */ }
    set({ mode })
  },
  toggle: () => {
    const next = get().mode === 'dark' ? 'light' : 'dark'
    get().setMode(next)
  },
}))

export function applyThemeMode(mode: ThemeMode) {
  if (typeof document === 'undefined') return
  document.documentElement.dataset.theme = mode
  document.documentElement.style.colorScheme = mode
}
