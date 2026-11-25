import { useMemo, useState, type FormEvent, type ReactNode } from 'react'
import { Button } from '@/components/ui/Button'
import { useConfirm } from '@/components/ui/confirm-context'
import { Input, PasswordInput } from '@/components/ui/Field'
import { Modal } from '@/components/ui/Modal'
import { ListSkeleton } from '@/components/ui/Skeleton'
import { useAuth } from '@/features/auth/AuthContext'
import { PASSWORD_HINT } from '@/features/settings/passwordPolicy'
import { limitTo, permissionsFromTicked, preset, summarize, tickedFromPermissions } from '../accessModel'
import { useCreateUser, usePermissionCatalog, useResetPassword, useUpdateUser, useUsers } from '../hooks'
import type { ManagedUser, PermissionGroup } from '../types'
import { AccessPicker, type AccessValue } from './AccessPicker'

function Actions({ onCancel, loading, label }: { onCancel: () => void; loading: boolean; label: string }) {
  return (
    <div className="flex justify-end gap-3">
      <Button type="button" variant="secondary" onClick={onCancel}>Cancel</Button>
      <Button type="submit" loading={loading}>{label}</Button>
    </div>
  )
}

/** The access checkmarks need the list of areas from the server; show a placeholder until it arrives. */
function WithCatalog({
  title,
  onClose,
  children,
}: { title: string; onClose: () => void; children: (catalog: PermissionGroup[]) => ReactNode }) {
  const catalog = usePermissionCatalog()
  return (
    <Modal open title={title} onClose={onClose} size="lg">
      {catalog.data ? (
        children(catalog.data)
      ) : catalog.error ? (
        <p role="alert" className="text-sm text-danger">{catalog.error.message}</p>
      ) : (
        <ListSkeleton rows={4} />
      )}
    </Modal>
  )
}

/** What the person using this form holds: it caps what they can hand out. */
function useActor() {
  const { user } = useAuth()
  return useMemo(
    () => ({ held: new Set(user?.permissions ?? []) as ReadonlySet<string>, canGrantAdmin: user?.role === 'admin' }),
    [user],
  )
}

// ---------- add user ----------

export function CreateUserModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  if (!open) return null
  return (
    <WithCatalog title="Add user" onClose={onClose}>
      {(catalog) => <CreateForm catalog={catalog} onClose={onClose} />}
    </WithCatalog>
  )
}

function CreateForm({ catalog, onClose }: { catalog: PermissionGroup[]; onClose: () => void }) {
  const create = useCreateUser()
  const confirm = useConfirm()
  const { held, canGrantAdmin } = useActor()
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  // New users start as "Read only": enough to look around, nothing that changes data.
  const [access, setAccess] = useState<AccessValue>(() => ({
    isAdmin: false,
    ticked: limitTo(catalog, preset(catalog, 'read'), held),
  }))

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    const permissions = permissionsFromTicked(catalog, access.ticked)
    const summary = summarize(catalog, permissions, access.isAdmin)
    const ok = await confirm({
      title: 'Create this user?',
      message: `${email.trim()} will be added with "${summary.label}" access and can sign in with the password you set.`,
      confirmLabel: 'Create user',
    })
    if (!ok) return
    create.mutate(
      {
        email: email.trim(),
        display_name: displayName.trim() || undefined,
        password,
        is_admin: access.isAdmin,
        permissions: access.isAdmin ? [] : permissions,
      },
      { onSuccess: onClose },
    )
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      <Input label="Email (used to sign in)" type="email" required maxLength={254} value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="off" />
      <Input label="Name (optional)" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
      <PasswordInput label="Temporary password" required value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
      <p className="-mt-2 text-xs text-muted">{PASSWORD_HINT}</p>
      <AccessPicker catalog={catalog} value={access} onChange={setAccess} canGrantAdmin={canGrantAdmin} actorPermissions={held} />
      {create.error && <p role="alert" className="text-sm text-danger">{create.error.message}</p>}
      <Actions onCancel={onClose} loading={create.isPending} label="Create user" />
    </form>
  )
}

// ---------- edit user ----------

export function EditUserModal({ user, onClose }: { user: ManagedUser | null; onClose: () => void }) {
  if (!user) return null
  return (
    <WithCatalog title={`Edit ${user.username}`} onClose={onClose}>
      {/* Remount per user so the form always starts from that user's values. */}
      {(catalog) => <EditForm key={user.user_id} user={user} catalog={catalog} onClose={onClose} />}
    </WithCatalog>
  )
}

function EditForm({ user, catalog, onClose }: { user: ManagedUser; catalog: PermissionGroup[]; onClose: () => void }) {
  const update = useUpdateUser()
  const confirm = useConfirm()
  const { held, canGrantAdmin } = useActor()
  const [displayName, setDisplayName] = useState(user.display_name ?? '')
  const [email, setEmail] = useState(user.email ?? '')
  const [active, setActive] = useState(user.is_active)
  const [leaveFrom, setLeaveFrom] = useState(user.on_leave_from ?? '')
  const [leaveUntil, setLeaveUntil] = useState(user.on_leave_until ?? '')
  const [backup, setBackup] = useState(user.delegate_user_id ?? '')
  const everyone = useUsers()
  const canApprove = user.is_admin || user.permissions.includes('approvals:write')
  const backups = (everyone.data ?? []).filter((u) => u.user_id !== user.user_id && u.is_active && (u.is_admin || u.permissions.includes('approvals:write')))
  const [access, setAccess] = useState<AccessValue>(() => ({
    isAdmin: user.is_admin,
    ticked: tickedFromPermissions(catalog, user.permissions),
  }))

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    const permissions = permissionsFromTicked(catalog, access.ticked)
    const deactivating = user.is_active && !active
    const adminChanged = access.isAdmin !== user.is_admin
    const before = new Set(user.permissions)
    const added = permissions.filter((p) => !before.has(p)).length
    const removed = user.is_admin ? 0 : user.permissions.filter((p) => !permissions.includes(p)).length
    const accessChanged = !access.isAdmin && !adminChanged && (added > 0 || removed > 0)
    const summary = summarize(catalog, permissions, access.isAdmin)

    const ok = await confirm({
      title: deactivating
        ? 'Deactivate this user?'
        : adminChanged
          ? access.isAdmin
            ? 'Make this user an administrator?'
            : 'Remove administrator access?'
          : accessChanged
            ? "Change this user's access?"
            : 'Save changes?',
      message: deactivating
        ? `${user.username} will be signed out immediately and won't be able to sign in until you reactivate the account.`
        : adminChanged
          ? access.isAdmin
            ? `${user.username} will be able to do everything, including managing users.`
            : `${user.username} will no longer be an administrator and will have "${summary.label}" access instead.`
          : accessChanged
            ? `${user.username} will have "${summary.label}" access (${added} added, ${removed} removed). It applies within seconds; they don't need to sign in again.`
            : `Update the details for ${user.username}.`,
      confirmLabel: deactivating ? 'Deactivate' : adminChanged || accessChanged ? 'Change access' : 'Save changes',
      tone: deactivating || (adminChanged && !access.isAdmin) ? 'danger' : 'default',
    })
    if (!ok) return

    update.mutate(
      {
        userId: user.user_id,
        body: {
          display_name: displayName.trim(),
          email: email.trim(),
          is_active: active,
          is_admin: access.isAdmin,
          // An administrator's access is "everything": there's no list to send.
          ...(access.isAdmin ? {} : { permissions }),
          // Leave and the backup are sent only when they changed (a save for another reason must not re-send the waiting approvals).
          ...(leaveFrom !== (user.on_leave_from ?? '') ? { on_leave_from: leaveFrom || null } : {}),
          ...(leaveUntil !== (user.on_leave_until ?? '') ? { on_leave_until: leaveUntil || null } : {}),
          ...(backup !== (user.delegate_user_id ?? '') ? { delegate_user_id: backup || null } : {}),
        },
      },
      { onSuccess: onClose },
    )
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      <Input label="Name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
      <Input label="Email" type="email" maxLength={254} value={email} onChange={(e) => setEmail(e.target.value)} />
      <AccessPicker catalog={catalog} value={access} onChange={setAccess} canGrantAdmin={canGrantAdmin} actorPermissions={held} />
      {canApprove && (
        <fieldset className="flex flex-col gap-3 rounded-xl border border-line p-4">
          <legend className="px-1 text-xs font-semibold text-title">Leave and backup approver</legend>
          <p className="text-xs text-muted">While away, orders that need approval go to the backup instead, and to the admins if there is none.</p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Input label="On leave from" type="date" value={leaveFrom} max={leaveUntil || undefined} onChange={(e) => setLeaveFrom(e.target.value)} />
            <Input label="Back on (last day away)" type="date" value={leaveUntil} min={leaveFrom || undefined} onChange={(e) => setLeaveUntil(e.target.value)} />
          </div>
          <label className="flex flex-col gap-1.5 text-xs font-medium text-muted">
            Backup approver
            <select
              value={backup}
              onChange={(e) => setBackup(e.target.value)}
              className="h-11 rounded-xl border border-line bg-white px-3 text-sm text-title focus:border-brand focus:outline-none focus:ring-4 focus:ring-brand/15"
            >
              <option value="">None</option>
              {backups.map((u) => (
                <option key={u.user_id} value={u.user_id}>
                  {u.display_name || u.username}
                  {u.email ? '' : ' (no e-mail address)'}
                </option>
              ))}
            </select>
          </label>
          {(leaveFrom || leaveUntil) && (
            <button type="button" className="self-start text-xs font-medium text-brand-ink hover:underline" onClick={() => { setLeaveFrom(''); setLeaveUntil('') }}>
              Clear the leave dates
            </button>
          )}
        </fieldset>
      )}
      <label className="flex cursor-pointer items-center gap-2.5 text-sm text-title">
        <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} className="h-4 w-4 accent-[#ea4d4e]" />
        Account is active
      </label>
      {!active && user.is_active && (
        <p className="rounded-xl bg-brand-tint px-4 py-2.5 text-xs text-brand-ink">Saving signs this user out of every device.</p>
      )}
      {update.error && <p role="alert" className="text-sm text-danger">{update.error.message}</p>}
      <Actions onCancel={onClose} loading={update.isPending} label="Save changes" />
    </form>
  )
}

// ---------- reset password ----------

export function ResetPasswordModal({ user, onClose }: { user: ManagedUser | null; onClose: () => void }) {
  return user ? <ResetForm key={user.user_id} user={user} onClose={onClose} /> : null
}

function ResetForm({ user, onClose }: { user: ManagedUser; onClose: () => void }) {
  const reset = useResetPassword()
  const confirm = useConfirm()
  const [password, setPassword] = useState('')

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    const ok = await confirm({
      title: 'Reset this password?',
      message: `${user.username} will be signed out of every device and must use the new password from now on.`,
      confirmLabel: 'Reset password',
      tone: 'danger',
    })
    if (!ok) return
    reset.mutate({ userId: user.user_id, password }, { onSuccess: onClose })
  }

  return (
    <Modal open title={`Reset password for ${user.username}`} onClose={onClose}>
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <PasswordInput label="New password" required value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
        <p className="-mt-2 text-xs text-muted">{PASSWORD_HINT} The user is signed out everywhere.</p>
        {reset.error && <p role="alert" className="text-sm text-danger">{reset.error.message}</p>}
        <Actions onCancel={onClose} loading={reset.isPending} label="Reset password" />
      </form>
    </Modal>
  )
}
