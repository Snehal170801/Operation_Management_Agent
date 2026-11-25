import { useState, type FormEvent } from 'react'
import { Check } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { useConfirm } from '@/components/ui/confirm-context'
import { Card } from '@/components/ui/Card'
import { Input } from '@/components/ui/Field'
import { useAuth } from '@/features/auth/AuthContext'
import { RoleBadge } from '@/features/users/components/RoleBadge'
import { InstallAppCard } from './InstallAppCard'
import { humanize } from '@/lib/format'

const MODULE_LABELS: Record<string, string> = {
  cases: 'Cases & purchase orders',
  storeroom: 'Store Room',
  audit: 'Audit log',
  users: 'Users',
  approvals: 'Approvals',
}

/** "Read only" / "CRUD" / "Own requests only", the same words as the access checkmarks on the Users screen. */
function levelFor(resource: string, actions: string[]): string {
  if (actions.includes('write')) return 'CRUD'
  if (resource === 'cases' && !actions.includes('read_all')) return 'Own requests only'
  return 'Read only'
}

function Permissions({ permissions, isAdmin }: { permissions: string[]; isAdmin: boolean }) {
  const grouped = permissions.reduce<Record<string, string[]>>((acc, p) => {
    const [resource, action] = p.split(':')
    ;(acc[resource] ??= []).push(action)
    return acc
  }, {})

  if (isAdmin) {
    return <p className="rounded-xl bg-brand-tint px-4 py-3 text-sm text-brand-ink">Administrator: full access to everything, including managing users.</p>
  }

  const rows = Object.entries(grouped)
  if (!rows.length) return <p className="text-sm text-muted">You don't have access to anything yet. Ask an administrator.</p>

  // One compact column: short enough that both cards fit on screen without scrolling.
  return (
    <ul className="divide-y divide-line rounded-xl border border-line">
      {rows.map(([resource, actions]) => (
        <li key={resource} className="flex items-center justify-between gap-3 px-4 py-2 text-sm">
          <span className="font-medium text-title">{MODULE_LABELS[resource] ?? humanize(resource)}</span>
          <span className="text-xs text-muted">{levelFor(resource, actions)}</span>
        </li>
      ))}
    </ul>
  )
}

export function ProfileSection() {
  const { user, updateProfile } = useAuth()
  const confirm = useConfirm()
  const [name, setName] = useState(user?.display_name ?? '')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!user) return null
  const unchanged = name.trim() === (user.display_name ?? '')

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    const ok = await confirm({
      title: 'Update your profile?',
      message: `Your display name will change to "${name.trim()}".`,
      confirmLabel: 'Save changes',
    })
    if (!ok) return
    setSaving(true)
    setError(null)
    setSaved(false)
    try {
      await updateProfile(name.trim())
      setSaved(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save your profile.')
    } finally {
      setSaving(false)
    }
  }

  return (
    // Side by side on wide screens so nothing needs scrolling; stacked on phones.
    <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-2">
      <Card title="Profile">
        <div className="mb-5 flex items-center gap-4">
          <span className="flex h-16 w-16 items-center justify-center rounded-full bg-brand-soft text-2xl font-semibold text-brand-ink">
            {(user.display_name || user.username).charAt(0).toUpperCase()}
          </span>
          <div>
            <p className="text-base font-semibold text-title">{user.display_name || user.username}</p>
            <p className="mb-1 text-xs text-muted">{user.email ?? user.username}</p>
            <RoleBadge role={user.role} />
          </div>
        </div>

        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <Input label="Display name" required maxLength={150} value={name} onChange={(e) => { setName(e.target.value); setSaved(false) }} />
          <Input label="Email (sign-in)" value={user.email ?? user.username} disabled readOnly className="bg-slate-50 text-muted" />
          {!user.email && (
            <p className="-mt-2 text-xs text-brand-ink">
              No email on file, so "Forgot password" can't reach you. Ask an administrator to add one.
            </p>
          )}
          {error && <p role="alert" className="text-sm text-danger">{error}</p>}
          <div className="flex items-center gap-3">
            <Button type="submit" loading={saving} disabled={unchanged || !name.trim()}>Save changes</Button>
            {saved && (
              <span className="flex items-center gap-1 text-sm font-medium text-[#16A34A]">
                <Check size={16} /> Saved
              </span>
            )}
          </div>
        </form>
      </Card>

      <Card title="Your access">
        <p className="mb-3 text-xs text-muted">What you can do in this app. Only an administrator can change it.</p>
        <Permissions permissions={user.permissions} isAdmin={user.role === 'admin'} />
      </Card>

      <InstallAppCard />
    </div>
  )
}
