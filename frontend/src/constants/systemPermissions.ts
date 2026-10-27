/** Module permission metadata is supplied by /auth/me. Project scope and
 * project.capabilities remain separate; these helpers never grant membership. */
export interface PermissionUser {
  id?: string
  role?: string
  system_permissions?: string[]
  permission_overrides?: Record<string, boolean>
  permission_version?: number
}

export const SYSTEM_PERMISSION_REFRESH_EVENT = 'agv:refresh-system-permissions'

/** Legacy /auth/me payloads inherit the established role defaults. New payloads
 * always use the server effective list, so this table cannot widen a grant. */
export const SYSTEM_PERMISSION_DEFAULTS: Record<string, readonly string[]> = {
  "system.holidays.read": ["admin", "director", "lead", "pm", "technician", "worker", "intern", "readonly"],
  "system.holidays.manage": ["admin"],
  "system.backups.configure": ["admin"],
  "personal.messages.use": ["admin", "director", "lead", "pm", "technician", "worker", "intern"],
  "personal.records.read": ["admin", "director", "lead", "pm", "technician", "worker", "intern"],
  "system.inventory.view": ["admin", "director", "lead", "pm", "technician"],
  "workspace.view": [
    "admin",
    "director",
    "lead",
    "pm",
    "technician"
  ],
  "insights.view": [
    "admin",
    "director",
    "lead",
    "pm",
    "technician"
  ],
  "personal.schedule.read": ["admin", "director", "lead", "pm", "technician", "worker", "intern"],
  "personal.schedule.manage": [
    "admin",
    "director",
    "lead",
    "pm",
    "technician"
  ],
  "worker.report": [
    "admin",
    "director",
    "lead",
    "pm",
    "technician",
    "worker",
    "intern"
  ],
  "worker.deliver": [
    "admin",
    "director",
    "lead",
    "pm",
    "technician",
    "worker",
    "intern"
  ],
  "worker.issues": [
    "admin",
    "director",
    "lead",
    "pm",
    "technician",
    "worker",
    "intern"
  ],
  "feedback.submit": [
    "admin",
    "director",
    "lead",
    "pm",
    "technician",
    "worker",
    "intern"
  ],
  "projects.create": [
    "admin",
    "pm"
  ],
  "projects.view_all": [
    "admin",
    "director"
  ],
  "project.read": [
    "admin",
    "director",
    "lead",
    "pm",
    "technician",
    "worker",
    "intern"
  ],
  "project.update": [
    "admin",
    "pm",
    "lead"
  ],
  "project.manage_members": [
    "admin",
    "pm",
    "lead"
  ],
  "project.manage_plan": [
    "admin",
    "pm",
    "lead",
    "technician"
  ],
  "project.manage_schedule": [
    "admin",
    "pm",
    "lead",
    "technician"
  ],
  "project.manage_issues": [
    "admin",
    "director",
    "pm",
    "lead",
    "technician"
  ],
  "project.export": [
    "admin",
    "director",
    "lead",
    "pm",
    "technician"
  ],
  "project.archive": [
    "admin",
    "director",
    "pm",
    "lead"
  ],
  "project.manage_inventory": [
    "admin",
    "director",
    "lead",
    "pm",
    "technician"
  ],
  "project.delete": [
    "admin"
  ],
  "system.import.create": [
    "admin",
    "pm"
  ],
  "system.archives.read": [
    "admin",
    "director"
  ],
  "system.users.read": [
    "admin"
  ],
  "system.users.manage": [
    "admin"
  ],
  "system.availability.manage": [
    "admin",
    "pm"
  ],
  "system.templates.read": [
    "admin",
    "director",
    "lead",
    "pm",
    "technician",
    "worker",
    "intern"
  ],
  "system.templates.view": [
    "admin"
  ],
  "system.templates.manage": [
    "admin"
  ],
  "system.template_io.manage": [
    "admin"
  ],
  "system.vehicle_types.view": [
    "admin"
  ],
  "system.vehicle_types.manage": [
    "admin"
  ],
  "system.inventory.read": [
    "admin",
    "director",
    "lead",
    "pm",
    "technician",
    "worker",
    "intern"
  ],
  "system.ai.use": [
    "admin",
    "director",
    "lead",
    "pm",
    "technician",
    "worker",
    "intern"
  ],
  "system.ai.configure": [
    "admin",
    "director",
    "lead",
    "pm",
    "technician",
    "worker",
    "intern"
  ],
  "system.agent_tokens.manage": [
    "admin"
  ],
  "system.agent.use": [
    "admin",
    "director",
    "lead",
    "pm",
    "technician",
    "worker",
    "intern"
  ],
  "system.skills.download": [
    "admin",
    "director",
    "lead",
    "pm",
    "technician",
    "worker",
    "intern"
  ],
  "permission.manage": [
    "admin"
  ],
  "system.notifications.configure": [
    "admin"
  ],
  "system.backups.read": [
    "admin"
  ],
  "system.backups.create": [
    "admin"
  ],
  "system.backups.download": [
    "admin"
  ],
  "system.backups.delete": [
    "admin"
  ],
  "system.backups.restore": [
    "admin"
  ],
  "system.audit.read": [
    "admin",
    "director",
    "lead",
    "pm",
    "technician",
    "worker",
    "intern"
  ],
  "system.feedback.manage": [
    "admin",
    "director",
    "pm"
  ]
}


const READ_ONLY_PERMISSION_KEYS = new Set([
  'workspace.view', 'insights.view', 'personal.schedule.read', 'personal.messages.use',
  'personal.records.read', 'project.read', 'project.export', 'projects.view_all',
  'system.templates.read', 'system.templates.view', 'system.vehicle_types.view',
  'system.inventory.read', 'system.inventory.view', 'system.archives.read', 'system.audit.read',
  'system.agent.use', 'system.skills.download',
])
for (const key of READ_ONLY_PERMISSION_KEYS) {
  const defaults = SYSTEM_PERMISSION_DEFAULTS[key]
  if (defaults?.includes('worker')) SYSTEM_PERMISSION_DEFAULTS[key] = [...defaults, 'readonly']
}

export function hasSystemPermission(
  user: PermissionUser | null | undefined,
  key: string,
  fallbackRoles?: readonly string[] | boolean,
): boolean {
  if (!user || !Object.prototype.hasOwnProperty.call(SYSTEM_PERMISSION_DEFAULTS, key)) return false
  if (user.role === 'readonly' && !READ_ONLY_PERMISSION_KEYS.has(key)) return false
  if (key === 'permission.manage') return user.role === 'admin'
  if (user.permission_overrides?.[key] === false) return false
  if (Array.isArray(user.system_permissions)) return user.system_permissions.includes(key)
  if (user.permission_overrides?.[key] === true) return true
  const fallback = fallbackRoles ?? SYSTEM_PERMISSION_DEFAULTS[key] ?? false
  return typeof fallback === 'boolean' ? fallback : fallback.includes(user.role ?? '')
}

export function hasAnySystemPermission(
  user: PermissionUser | null | undefined,
  keys: readonly string[],
  fallbackRoles?: readonly string[] | boolean,
): boolean {
  return keys.some(key => hasSystemPermission(user, key, fallbackRoles))
}
