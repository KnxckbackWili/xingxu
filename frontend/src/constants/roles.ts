/** Two kinds of account: a system administrator, or an employee who does all project work. */
export type Role = 'admin' | 'employee'

export const ROLE_NAME: Record<string, string> = { admin: '系统管理员', employee: '员工' }

export const ROLE_TAG: Record<string, { label: string; color: string }> = {
  admin: { label: '管理员', color: 'red' },
  employee: { label: '员工', color: 'blue' },
}

export const isAdmin = (role?: string) => role === 'admin'
