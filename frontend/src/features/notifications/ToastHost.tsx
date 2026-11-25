import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Activity, AlertTriangle, Bell, CheckCircle2, FileText, ShieldCheck, X } from 'lucide-react'
import clsx from 'clsx'
import { AnimatePresence, MotionConfig, motion } from 'motion/react'
import { useAuth } from '@/features/auth/AuthContext'
import { showDesktop } from './desktop'
import { useNotifications, type AppNotification } from './hooks'

const ICON: Record<string, typeof Bell> = { approval: ShieldCheck, case: AlertTriangle, invoice: FileText, my_request: CheckCircle2, system: Activity }
const MAX_SHOWN = 3
/** Something that needs a person stays up longer than a progress update. */
const STAY_MS = { action: 20_000, info: 9_000 }

function Toast({ item, onDismiss }: { item: AppNotification; onDismiss: (id: string) => void }) {
  const Icon = ICON[item.kind] ?? Bell
  useEffect(() => {
    const timer = setTimeout(() => onDismiss(item.id), item.requires_action ? STAY_MS.action : STAY_MS.info)
    return () => clearTimeout(timer)
  }, [item, onDismiss])

  return (
    <motion.div
      layout
      initial={{ opacity: 0, x: 40, scale: 0.97 }}
      animate={{ opacity: 1, x: 0, scale: 1 }}
      exit={{ opacity: 0, x: 40, scale: 0.97 }}
      transition={{ duration: 0.25, ease: 'easeOut' }}
      className={clsx(
        'pointer-events-auto flex gap-3 overflow-hidden rounded-2xl border bg-white p-4 shadow-[0_8px_30px_rgba(15,23,42,0.18)]',
        item.requires_action ? 'border-brand/40' : 'border-line',
      )}
    >
      <span className={clsx('mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full', item.requires_action ? 'bg-brand-soft text-brand-ink' : 'bg-emerald-100 text-emerald-700')}>
        <Icon size={18} />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-title">{item.title}</p>
        <p className="mt-0.5 line-clamp-3 break-words text-sm text-muted">{item.message}</p>
        <Link
          to={item.link}
          onClick={() => onDismiss(item.id)}
          className="mt-2 inline-flex h-8 items-center rounded-lg bg-brand px-3 text-xs font-semibold text-white hover:opacity-90"
        >
          {item.requires_action ? 'Review' : 'View'}
        </Link>
      </div>
      <button
        type="button"
        onClick={() => onDismiss(item.id)}
        aria-label="Dismiss"
        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-muted hover:bg-brand-tint"
      >
        <X size={14} />
      </button>
    </motion.div>
  )
}

/** A pop-up the moment something NEW reaches your bell: a job for your department, or progress on your request.
 *  It reads the same feed as the bell (so it only ever shows what is yours) and the live connection refreshes that
 *  feed the instant something changes. What was already there when the page opened is not announced again. */
export function ToastHost() {
  const { can } = useAuth()
  const { data } = useNotifications(can('cases:read'))
  const seen = useRef<Set<string> | null>(null)
  const [toasts, setToasts] = useState<AppNotification[]>([])

  useEffect(() => {
    if (!data) return
    if (seen.current === null) {
      seen.current = new Set(data.map((n) => n.id)) // what is already waiting is not news
      return
    }
    const known = seen.current
    const fresh = data.filter((n) => !known.has(n.id))
    if (!fresh.length) return
    fresh.forEach((n) => {
      known.add(n.id)
      if (n.requires_action) showDesktop(n.title, n.message, n.link, n.id)
    })
    setToasts((current) => [...fresh, ...current].slice(0, MAX_SHOWN))
  }, [data])

  const dismiss = useCallback((id: string) => setToasts((current) => current.filter((t) => t.id !== id)), [])

  return (
    <MotionConfig reducedMotion="user">
      <div role="status" aria-live="polite" className="pointer-events-none fixed bottom-4 right-4 z-[70] flex w-[min(92vw,390px)] flex-col gap-3">
        <AnimatePresence initial={false}>
          {toasts.map((t) => (
            <Toast key={t.id} item={t} onDismiss={dismiss} />
          ))}
        </AnimatePresence>
      </div>
    </MotionConfig>
  )
}
