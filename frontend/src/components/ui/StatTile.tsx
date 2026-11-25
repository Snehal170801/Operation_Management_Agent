import type { ReactNode } from 'react'
import clsx from 'clsx'
import { StatTileSkeleton } from './Skeleton'

interface StatTileProps {
  /** Show the placeholder tile instead of a misleading 0 while the numbers load. */
  loading?: boolean
  icon: ReactNode
  label: string
  value: number | string
  note?: string
  noteTone?: 'muted' | 'good' | 'bad'
  delayMs?: number
}

const NOTE_COLOR = { muted: 'text-muted', good: 'text-green-600', bad: 'text-danger' } as const

/** KPI tile: label, big number and note on the left; soft brand square with the icon on the right. */
export function StatTile({ loading, icon, label, value, note, noteTone = 'muted', delayMs = 0 }: StatTileProps) {
  if (loading) return <StatTileSkeleton />
  const text = typeof value === 'number' ? value.toLocaleString() : value
  // A long figure steps down in size (and, as a last resort, truncates) so it can never run under the icon.
  const size = text.length > 9 ? 'text-[22px]' : text.length > 7 ? 'text-[26px]' : text.length > 5 ? 'text-[29px]' : 'text-[32px]'
  return (
    <div
      className="dash-fade-in flex h-[124px] items-start justify-between gap-3 rounded-2xl border border-card-border bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]"
      style={{ animationDelay: `${delayMs}ms` }}
    >
      <div className="min-w-0 flex-1 text-left">
        <p className="truncate text-xs font-medium text-muted">{label}</p>
        <p
          className={clsx('mt-1 truncate font-semibold leading-none tracking-tight tabular-nums text-title', size)}
          title={text}
        >
          {text}
        </p>
        {note && <p className={clsx('mt-2 truncate text-xs', NOTE_COLOR[noteTone])}>{note}</p>}
      </div>
      <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-brand-soft text-brand-ink">
        {icon}
      </span>
    </div>
  )
}
