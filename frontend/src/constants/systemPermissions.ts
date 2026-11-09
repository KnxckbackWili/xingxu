/** What an account may do. Administrators do everything; employees do all project work.
 * The server is authoritative; this mirrors it for showing or hiding entries. */
export interface PermissionUser {
  id?: string
  role?: string
  is_active?: boolean
  system_permissions?: string[]
}

/** Fired when the server says this account's role or session changed, so /auth/me is read again. */
export const SYSTEM_PERMISSION_REFRESH_EVENT = 'agv:refresh-system-permissions'

/** Actions only a system administrator may take (mirrors backend ADMIN_ONLY). */
export const ADMIN_ONLY_PERMISSIONS = new Set([
  'system.projects.purge', 'system.users.read', 'system.users.manage', 'system.holidays.manage',
  'system.notifications.configure', 'system.backups.read', 'system.backups.configure', 'system.backups.create',
  'system.backups.download', 'system.backups.delete', 'system.backups.restore',
])

export function hasSystemPermission(user: PermissionUser | null | undefined, key: string): boolean {
  if (!user || user.is_active === false) return false
  if (Array.isArray(user.system_permissions)) return user.system_permissions.includes(key)
  return user.role === 'admin' || !ADMIN_ONLY_PERMISSIONS.has(key)
}

export function hasAnySystemPermission(user: PermissionUser | null | undefined, keys: readonly string[]): boolean {
  return keys.some(key => hasSystemPermission(user, key))
}
