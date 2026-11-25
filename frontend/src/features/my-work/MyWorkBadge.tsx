import clsx from 'clsx'
import { useMyWork } from './hooks'

/** How much is waiting for this person, shown beside "My work" in the menu. Red when anything is urgent. */
export function MyWorkBadge({ collapsed }: { collapsed: boolean }) {
  const { data } = useMyWork()
  const total = data?.total ?? 0
  if (total === 0) return null
  const urgent = data?.queues.some((q) => q.items.some((i) => i.urgent)) ?? false
  const label = `${total} waiting${urgent ? ', some urgent' : ''}`

  if (collapsed) {
    return <span role="status" aria-label={label} className={clsx('absolute right-2 top-2 h-2.5 w-2.5 rounded-full ring-2 ring-white', urgent ? 'bg-danger' : 'bg-slate-500')} />
  }
  return (
    <span
      role="status"
      aria-label={label}
      className={clsx(
        'ml-auto grid h-5 min-w-5 place-items-center rounded-full px-1.5 text-[11px] font-semibold text-white',
        urgent ? 'bg-danger' : 'bg-slate-500',
      )}
    >
      {total > 99 ? '99+' : total}
    </span>
  )
}
