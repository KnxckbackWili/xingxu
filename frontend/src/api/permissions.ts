import { api } from './client'

export interface PermissionDefinition {
  key: string
  name: string
  description: string
  scope: string
  risk: string
  default_roles: string[]
  admin_locked?: boolean
  contextual_default?: boolean
  read_only?: boolean
}

export interface PermissionGroup {
  key: string
  name: string
  description: string
  permissions: PermissionDefinition[]
}

export interface PermissionCatalog {
  groups: PermissionGroup[]
  roles: { key: string; name: string }[]
}

export interface PermissionMember {
  id: string
  username: string
  display_name: string
  role: string
  is_active: boolean
  permission_version: number
}

export type PermissionOverrides = Record<string, boolean>

export interface MemberPermissions {
  user: PermissionMember
  version: number
  overrides: PermissionOverrides
  effective: string[]
  defaults: string[]
}

export interface PermissionReason {
  key: string; name: string; allowed: boolean; layer: string; reason: string
}

export const permissionsApi = {
  projectReasons: async (projectId: string, userId: string): Promise<{ items: PermissionReason[] }> =>
    (await api.get(`/permissions/projects/${encodeURIComponent(projectId)}/users/${encodeURIComponent(userId)}/reasons`)).data,
  catalog: async (): Promise<PermissionCatalog> => (await api.get('/permissions/catalog')).data,
  users: async (): Promise<PermissionMember[]> => {
    const { data } = await api.get<PermissionMember[] | { items: PermissionMember[] }>('/permissions/users')
    return Array.isArray(data) ? data : data.items
  },
  getUser: async (id: string): Promise<MemberPermissions> => (await api.get(`/permissions/users/${encodeURIComponent(id)}`)).data,
  updateUser: async (id: string, body: { version: number; overrides: PermissionOverrides }): Promise<MemberPermissions> =>
    (await api.put(`/permissions/users/${encodeURIComponent(id)}`, body)).data,
}
