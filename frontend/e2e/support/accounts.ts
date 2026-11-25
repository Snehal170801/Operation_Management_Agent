// The fixed accounts created by backend/scripts/e2e_env.py (seed). One shared password.
export const PASSWORD = 'E2eTest@2026!'
export const API = process.env.E2E_API_URL ?? 'http://localhost:8100'

export const ADMIN = 'admin'
export const MANAGER = 'manager'
export const REQUESTER = 'requester'
export const REQUESTER2 = 'requester2'
export const DEPARTMENTS = ['purchase', 'stores', 'vendor', 'approval', 'po', 'receiving', 'accounts'] as const
export const ALL_ACCOUNTS = [ADMIN, MANAGER, REQUESTER, REQUESTER2, ...DEPARTMENTS]
