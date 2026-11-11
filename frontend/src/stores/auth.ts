import { create } from 'zustand'
import { api } from '../api/client'
import type { User } from '../api/types'

interface AuthState {
  user: User | null
  loading: boolean
  failed: boolean
  login: (username: string, password: string) => Promise<User>
  logout: () => Promise<void>
  fetchMe: () => Promise<void>
}

export const useAuth = create<AuthState>((set, get) => ({
  user: null,
  loading: false,
  failed: false,
  login: async (username, password) => {
    const { data } = await api.post('/auth/login', { username, password })
    set({ user: data.user, failed: false })
    return data.user
  },
  logout: async () => {
    set({ user: null })
    await api.post('/auth/logout').catch(() => undefined)
  },
  fetchMe: async () => {
    if (get().loading) return
    set({ loading: true, failed: false })
    try {
      const { data } = await api.get('/auth/me')
      set({ user: data, loading: false })
    } catch {
      set({ user: null, loading: false, failed: true })
    }
  },
}))
