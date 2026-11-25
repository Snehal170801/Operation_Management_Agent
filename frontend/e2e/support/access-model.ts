// What each seeded account is MEANT to be allowed to do. Copied from the product's own rules (backend/app/core/permissions.py:
// DEFAULT_ROLE_PERMISSIONS and DEPARTMENTS). If the product's rules change on purpose, change this table with them; if they change
// by accident, the access tests fail.
const BASE = ['dashboard:read', 'cases:read', 'cases:read_all']
const VIEW = ['dashboard:read', 'cases:read', 'stock:read', 'vendors:read', 'approvals:read']

export const PERMISSIONS: Record<string, string[] | 'all'> = {
  admin: 'all',
  manager: [...VIEW, 'cases:read_all', 'storeroom:read', 'cases:create', 'cases:write', 'stock:write', 'vendors:write', 'approvals:write', 'po:manage', 'delivery:confirm', 'invoices:decide'],
  requester: ['cases:read', 'cases:create'],
  requester2: ['cases:read', 'cases:create'],
  purchase: [...BASE, 'cases:create', 'cases:write', 'storeroom:read'],
  stores: [...BASE, 'stock:read', 'stock:write', 'storeroom:read'],
  vendor: [...BASE, 'vendors:read', 'vendors:write', 'stock:read'],
  approval: [...BASE, 'approvals:read', 'approvals:write', 'vendors:read'],
  po: [...BASE, 'po:manage', 'vendors:read'],
  receiving: [...BASE, 'delivery:confirm'],
  accounts: [...BASE, 'invoices:decide'],
}

export const can = (account: string, permission: string) => {
  const p = PERMISSIONS[account]
  return p === 'all' || p.includes(permission)
}

/** Read endpoints and the one permission each needs. */
export const READ_ENDPOINTS: { path: string; permission: string }[] = [
  { path: '/stock', permission: 'stock:read' },
  { path: '/vendors', permission: 'vendors:read' },
  { path: '/approvals', permission: 'approvals:read' },
  { path: '/users', permission: 'users:read' },
  { path: '/audit', permission: 'audit:read' },
  { path: '/my-work', permission: 'cases:read_all' },
  { path: '/system/health', permission: 'system:read' },
]
