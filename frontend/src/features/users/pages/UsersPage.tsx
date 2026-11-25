import { useMemo, useState } from 'react'
import { KeyRound, Lock, Pencil, Plus, Search, Trash2, Unlock, UserCheck, UserX } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { useConfirm } from '@/components/ui/confirm-context'
import { Card } from '@/components/ui/Card'
import { DEFAULT_PAGE_SIZE, Pagination } from '@/components/ui/Pagination'
import { QueryState } from '@/components/ui/QueryState'
import { Table, Td, Tr } from '@/components/ui/Table'
import { useAuth } from '@/features/auth/AuthContext'
import { formatDate, formatDateTime } from '@/lib/format'
import { CreateUserModal, EditUserModal, ResetPasswordModal } from '../components/UserModals'
import { AccessBadge } from '../components/AccessBadge'
import { useDeleteUser, usePermissionCatalog, useUnlockUser, useUpdateUser, useUsers } from '../hooks'
import type { ManagedUser } from '../types'

const iconBtn =
  'flex h-10 w-10 md:h-8 md:w-8 items-center justify-center rounded-lg bg-brand-tint text-brand-ink transition-colors hover:bg-brand-soft'

export function UsersPage() {
  const { user: me, can } = useAuth()
  const canWrite = can('users:write')
  const { data, isLoading, error } = useUsers()
  const unlock = useUnlockUser()
  const update = useUpdateUser()
  const remove = useDeleteUser()
  const [actionError, setActionError] = useState<string | null>(null)
  const catalog = usePermissionCatalog()
  const confirm = useConfirm()

  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<ManagedUser | null>(null)
  const [resetting, setResetting] = useState<ManagedUser | null>(null)
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return (data ?? []).filter(
      (u) => !q || u.username.toLowerCase().includes(q) || (u.email ?? '').toLowerCase().includes(q) || (u.display_name ?? '').toLowerCase().includes(q),
    )
  }, [data, search])
  const rows = filtered.slice((page - 1) * pageSize, page * pageSize)

  async function setActive(u: ManagedUser, active: boolean) {
    const ok = await confirm({
      title: active ? 'Activate this user?' : 'Deactivate this user?',
      message: active
        ? `${u.username} will be able to sign in again.`
        : `${u.username} will be signed out everywhere and can't sign in until you activate them again. Their history is kept.`,
      confirmLabel: active ? 'Activate' : 'Deactivate',
    })
    if (!ok) return
    setActionError(null)
    update.mutate({ userId: u.user_id, body: { is_active: active } }, { onError: (e) => setActionError(e.message) })
  }

  async function deleteUser(u: ManagedUser) {
    const ok = await confirm({
      title: 'Delete this user permanently?',
      message: `${u.username} will be removed for good and can't be brought back. Their past requests and approvals stay in the records under their name. If they might return, deactivate them instead.`,
      confirmLabel: 'Delete user',
    })
    if (!ok) return
    setActionError(null)
    remove.mutate(u.user_id, { onError: (e) => setActionError(e.message) })
  }

  return (
    <div className="flex w-full flex-col xl:h-full">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 pb-4">
        <h1 className="page-title">User Management</h1>
        {canWrite && (
          <Button onClick={() => setCreating(true)}>
            <Plus size={18} /> Add user
          </Button>
        )}
      </div>

      <Card className="flex-1" bodyClassName="flex min-h-0 flex-col p-0">
        <div className="shrink-0 border-b border-line px-5 py-3">
          <div className="relative max-w-xs">
            <Search size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" />
            <input
              value={search}
              onChange={(e) => {
                setSearch(e.target.value)
                setPage(1)
              }}
              placeholder="Search name or email"
              className="h-10 w-full rounded-xl border border-line pl-10 pr-3 text-sm focus:border-brand focus:outline-none focus:ring-4 focus:ring-brand/15"
            />
          </div>
        </div>

        {actionError && <p className="shrink-0 border-b border-line px-5 py-2 text-sm text-danger" role="alert">{actionError}</p>}

        <QueryState variant="table" columns={6} isLoading={isLoading} error={error} isEmpty={!filtered.length} emptyMessage="No users found.">
          <Table headers={canWrite ? ['Sr.No.', 'User', 'Access', 'Status', 'Last sign-in', 'Actions'] : ['Sr.No.', 'User', 'Access', 'Status', 'Last sign-in']}>
            {rows.map((u, i) => {
              const isMe = u.user_id.toLowerCase() === me?.user_id.toLowerCase()
              return (
                <Tr key={u.user_id}>
                  <Td first>{String((page - 1) * pageSize + i + 1).padStart(2, '0')}.</Td>
                  <Td>
                    <span className="block font-medium">
                      {u.display_name || u.username}
                      {isMe && <span className="ml-2 text-[11px] font-semibold text-brand-ink">(you)</span>}
                    </span>
                    <span className="block text-xs text-muted">{u.email ?? 'No email'}</span>
                  </Td>
                  <Td><AccessBadge user={u} catalog={catalog.data} /></Td>
                  <Td>
                    {!u.is_active ? (
                      <span className="inline-flex rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-semibold text-slate-600">Inactive</span>
                    ) : u.is_locked ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-danger-soft px-2.5 py-1 text-[11px] font-semibold text-danger">
                        <Lock size={11} /> Locked
                      </span>
                    ) : (
                      <span className="inline-flex rounded-full bg-[#DCFCE7] px-2.5 py-1 text-[11px] font-semibold text-[#16A34A]">Active</span>
                    )}
                    {u.is_active && u.on_leave_now && (
                      <span className="mt-1 block text-[11px] font-medium text-brand-ink">
                        On leave{u.on_leave_until ? ` until ${formatDate(u.on_leave_until)}` : ''} · {u.delegate_name ? `backup: ${u.delegate_name}` : 'no backup'}
                      </span>
                    )}
                  </Td>
                  <Td>{u.last_login_at ? formatDateTime(u.last_login_at) : 'Never'}</Td>
                  {canWrite && (
                    <Td>
                      <div className="flex gap-2">
                        <button type="button" className={iconBtn} title="Edit" aria-label={`Edit ${u.username}`} onClick={() => setEditing(u)}>
                          <Pencil size={15} />
                        </button>
                        <button type="button" className={iconBtn} title="Reset password" aria-label={`Reset password for ${u.username}`} onClick={() => setResetting(u)}>
                          <KeyRound size={15} />
                        </button>
                        {!isMe && (
                          <button
                            type="button"
                            className={iconBtn}
                            title={u.is_active ? 'Deactivate' : 'Activate'}
                            aria-label={`${u.is_active ? 'Deactivate' : 'Activate'} ${u.username}`}
                            disabled={update.isPending}
                            onClick={() => void setActive(u, !u.is_active)}
                          >
                            {u.is_active ? <UserX size={15} /> : <UserCheck size={15} />}
                          </button>
                        )}
                        {!isMe && (
                          <button
                            type="button"
                            className={iconBtn + ' !text-danger hover:!bg-danger-soft'}
                            title="Delete"
                            aria-label={`Delete ${u.username}`}
                            disabled={remove.isPending}
                            onClick={() => void deleteUser(u)}
                          >
                            <Trash2 size={15} />
                          </button>
                        )}
                        {u.is_locked && (
                          <button
                            type="button"
                            className={iconBtn}
                            title="Unlock account"
                            aria-label={`Unlock ${u.username}`}
                            disabled={unlock.isPending}
                            onClick={async () => {
                              const ok = await confirm({
                                title: 'Unlock this account?',
                                message: `${u.username} will be able to try signing in again right away.`,
                                confirmLabel: 'Unlock',
                              })
                              if (ok) unlock.mutate(u.user_id)
                            }}
                          >
                            <Unlock size={15} />
                          </button>
                        )}
                      </div>
                    </Td>
                  )}
                </Tr>
              )
            })}
          </Table>
        </QueryState>

        <Pagination
          page={page}
          pageSize={pageSize}
          totalItems={filtered.length}
          onPageChange={setPage}
          onPageSizeChange={(n) => {
            setPageSize(n)
            setPage(1)
          }}
          itemLabel="users"
        />
      </Card>

      <CreateUserModal open={creating} onClose={() => setCreating(false)} />
      <EditUserModal user={editing} onClose={() => setEditing(null)} />
      <ResetPasswordModal user={resetting} onClose={() => setResetting(null)} />
    </div>
  )
}
