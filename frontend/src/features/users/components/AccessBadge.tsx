import clsx from 'clsx'
import { summarize, type AccessSummary } from '../accessModel'
import type { ManagedUser, PermissionGroup } from '../types'

const TONES: Record<AccessSummary['tone'], string> = {
  admin: 'bg-brand-soft text-brand-ink',
  full: 'bg-[#DCFCE7] text-[#16A34A]',
  read: 'bg-slate-100 text-slate-600',
  custom: 'bg-[#DBEAFE] text-[#1D4ED8]',
  none: 'bg-danger-soft text-danger',
}

/** A one-word summary of a user's access ("Read only", "Full CRUD", "Custom"...); hover for the detail. */
export function AccessBadge({ user, catalog }: { user: ManagedUser; catalog: PermissionGroup[] | undefined }) {
  if (!catalog) return <span className="text-xs text-muted">…</span>
  const summary = summarize(catalog, user.permissions, user.is_admin)
  return (
    <span
      title={summary.lines.join('\n') || undefined}
      className={clsx('inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-semibold', TONES[summary.tone])}
    >
      {summary.label}
    </span>
  )
}
