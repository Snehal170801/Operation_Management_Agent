import { useEffect, useRef, useState } from 'react'
import { ListSkeleton } from '@/components/ui/Skeleton'
import { Link } from 'react-router-dom'
import { Activity, AlertTriangle, Bell, CheckCircle2, FileText, ShieldCheck } from 'lucide-react'
import clsx from 'clsx'
import { useAuth } from '@/features/auth/AuthContext'
import { formatDateTime } from '@/lib/format'
import { enableDesktop, useDesktopState } from './desktop'
import { readSeenAt, toTime, useNotifications, writeSeenAt, type AppNotification } from './hooks'

const ICON: Record<string, typeof Bell> = {
  approval: ShieldCheck,
  case: AlertTriangle,
  invoice: FileText,
  my_request: CheckCircle2,
  system: Activity,
}

/** Bell with a live count and a dropdown. Staff: things waiting on a person. Requesters: progress on their requests. */
export function NotificationBell() {
  const { user, can } = useAuth()
  const desktop = useDesktopState()
  const { data, isLoading, error } = useNotifications(can('cases:read'))
  const [open, setOpen] = useState(false)
  const [seenAt, setSeenAt] = useState(() => (user ? readSeenAt(user.user_id) : 0))
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const items = data ?? []
  // Action items count until they are dealt with; informational ones count until the bell is opened.
  const isNew = (n: AppNotification) => n.requires_action || toTime(n.created_at) > seenAt
  const unread = items.filter(isNew).length

  function toggle() {
    const next = !open
    setOpen(next)
    if (!next && user) {
      // Mark as seen when the panel is closed, so the list doesn't reshuffle while it is being read.
      const now = Date.now()
      writeSeenAt(user.user_id, now)
      setSeenAt(now)
    }
  }

  function close() {
    setOpen(false)
    if (user) {
      const now = Date.now()
      writeSeenAt(user.user_id, now)
      setSeenAt(now)
    }
  }

  if (!can('cases:read')) return null

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={toggle}
        aria-label={unread ? `Notifications, ${unread} new` : 'Notifications'}
        aria-expanded={open}
        className="relative flex h-10 w-10 items-center justify-center rounded-full bg-brand-tint transition-colors hover:bg-brand-soft"
      >
        <Bell size={18} className="text-brand-ink" />
        {unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-danger px-1 text-[10px] font-semibold text-white">
            {unread > 9 ? '9+' : unread}
          </span>
        )}
      </button>

      {open && (
        // Phones: a panel pinned under the top bar, 12px in from both edges (anchoring to the bell would push it
        // off the left side). From `sm` up it hangs under the bell as before.
        <div className="fixed inset-x-3 top-[68px] z-50 overflow-hidden rounded-xl border border-line bg-white shadow-lg sm:absolute sm:inset-x-auto sm:right-0 sm:top-[calc(100%+8px)] sm:w-[380px]">
          <div className="flex items-center justify-between border-b border-line px-4 py-3">
            <h2 className="text-sm font-semibold text-title">Notifications</h2>
            {unread > 0 && <span className="text-xs text-muted">{unread} new</span>}
          </div>

          {can('cases:read_all') && desktop === 'default' && (
            <div className="flex items-center justify-between gap-3 border-b border-line bg-brand-tint/50 px-4 py-2.5">
              <p className="text-xs text-title">Get a pop-up when something needs you, even if this tab is in the background.</p>
              <button type="button" onClick={() => void enableDesktop()} className="shrink-0 rounded-lg bg-brand px-3 py-1.5 text-xs font-semibold text-white hover:opacity-90">
                Turn on
              </button>
            </div>
          )}
          {can('cases:read_all') && desktop === 'denied' && (
            <p className="border-b border-line bg-amber-50 px-4 py-2 text-xs text-amber-900">Desktop pop-ups are blocked. Allow notifications for this site in your browser settings to get them.</p>
          )}

          <div className="max-h-[420px] overflow-y-auto">
            {isLoading && <ListSkeleton rows={3} />}
            {error && <p className="px-4 py-6 text-sm text-danger">Could not load notifications.</p>}
            {!isLoading && !error && items.length === 0 && (
              <p className="px-4 py-8 text-center text-sm text-muted">
                {can('cases:read_all') ? "Nothing needs your attention. The agents are handling it." : 'No updates yet.'}
              </p>
            )}
            <ul className="divide-y divide-line">
              {items.map((n) => {
                const Icon = ICON[n.kind] ?? Bell
                return (
                  <li key={n.id}>
                    <Link
                      to={n.link}
                      onClick={close}
                      className={clsx(
                        'flex gap-3 px-4 py-3 transition-colors hover:bg-brand-tint/60',
                        isNew(n) && 'bg-brand-tint/40',
                      )}
                    >
                      <span
                        className={clsx(
                          'mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full',
                          n.requires_action ? 'bg-danger-soft text-danger' : 'bg-[#DCFCE7] text-[#16A34A]',
                        )}
                      >
                        <Icon size={16} />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-sm font-semibold text-title">{n.title}</span>
                        <span className="block text-xs text-muted">{n.message}</span>
                        <span className="mt-0.5 block text-[11px] text-muted/80">{formatDateTime(n.created_at)}</span>
                      </span>
                    </Link>
                  </li>
                )
              })}
            </ul>
          </div>
        </div>
      )}
    </div>
  )
}
