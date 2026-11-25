import { ChevronDown, ExternalLink, Loader2, UserRound } from 'lucide-react'
import clsx from 'clsx'
import { useAuth } from '@/features/auth/AuthContext'
import { useDepartments, useUsers } from '@/features/users/hooks'
import { useOpenAccount } from './useOpenAccount'

const LABEL = 'Accounts'

/** Sidebar section for administrators: one entry per department's account (the human side of each agent) plus the
 *  other non-admin accounts. Clicking one opens that account in a NEW tab, no password needed, so you can watch
 *  what each person sees side by side. Every use is recorded in the audit log. */
export function AccountsNav({ closed, onToggle }: { closed: boolean; onToggle: () => void }) {
  const { can } = useAuth()
  const isAdmin = can('users:write') && can('system:write')
  const users = useUsers(isAdmin)
  const departments = useDepartments(isAdmin)
  const { open, busy, error } = useOpenAccount()

  if (!isAdmin) return null
  const people = (users.data ?? []).filter((u) => !u.is_admin && u.is_active)

  const matched = new Set<string>()
  const agents = (departments.data ?? []).flatMap((d) => {
    const person = people.find((u) => u.display_name === d.label)
    if (!person) return []
    matched.add(person.user_id)
    return [{ id: person.user_id, label: d.label, sub: d.agent, who: person.username }]
  })
  const others = people.filter((u) => !matched.has(u.user_id)).map((u) => ({ id: u.user_id, label: u.display_name || u.username, sub: 'Requester', who: u.username }))
  if (!agents.length && !others.length) return null

  const row = (item: { id: string; label: string; sub: string; who: string }) => (
    <button
      key={item.id}
      type="button"
      onClick={() => void open(item.id)}
      disabled={busy === item.id}
      title={`Open ${item.who} in a new tab`}
      aria-label={`Open ${item.label} in a new tab`}
      className="mb-1 flex h-10 w-full items-center gap-3 rounded-lg px-3 text-left text-[14px] font-medium text-muted transition-colors duration-150 hover:bg-brand-tint disabled:opacity-60"
    >
      <UserRound size={18} strokeWidth={2.2} className="shrink-0" />
      <span className="min-w-0 flex-1">
        <span className="block truncate">{item.label}</span>
        <span className="block truncate text-[11px] font-normal text-muted/80">{item.sub}</span>
      </span>
      {busy === item.id ? <Loader2 size={15} className="shrink-0 animate-spin" /> : <ExternalLink size={14} className="shrink-0 text-muted/60" />}
    </button>
  )

  return (
    <div role="group" aria-label={LABEL} className="mt-3">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={!closed}
        aria-controls="sidebar-group-accounts"
        className="mb-1 flex h-8 w-full items-center justify-between rounded-lg px-3 text-[11px] font-semibold uppercase tracking-wider text-muted/80 transition-colors hover:bg-brand-tint hover:text-title"
      >
        <span>{LABEL}</span>
        <ChevronDown size={14} strokeWidth={2.4} className={clsx('transition-transform duration-200', closed && '-rotate-90')} />
      </button>
      <div id="sidebar-group-accounts" className={clsx('grid transition-[grid-template-rows] duration-200 ease-in-out', closed ? 'grid-rows-[0fr]' : 'grid-rows-[1fr]')}>
        <div className="overflow-hidden" inert={closed}>
          {agents.length > 0 && <p className="px-3 pb-1 pt-0.5 text-[11px] text-muted/70">Agents · opens in a new tab</p>}
          {agents.map(row)}
          {others.length > 0 && <p className="px-3 pb-1 pt-2 text-[11px] text-muted/70">Others</p>}
          {others.map(row)}
          {error && <p role="alert" className="px-3 pb-1 text-xs text-danger">{error}</p>}
        </div>
      </div>
    </div>
  )
}
