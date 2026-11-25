import { BellRing, ClipboardList, type LucideIcon } from 'lucide-react'
import clsx from 'clsx'
import type { SupportAgent } from '../types'

const ICON: Record<SupportAgent['key'], LucideIcon> = { operations: ClipboardList, notification: BellRing }

const TONE: Record<SupportAgent['state'], { orb: string; pill: string; word: string; accent: string }> = {
  idle: { orb: 'border border-white/10 bg-white/5 text-white/40', pill: 'bg-white/10 text-white/60', word: 'Standing by', accent: 'before:bg-white/20' },
  active: { orb: 'bg-brand/25 text-rose-200', pill: 'bg-brand/25 text-rose-100', word: 'Working', accent: 'before:bg-brand' },
  done: { orb: 'bg-emerald-400/15 text-emerald-300 shadow-[0_0_18px_rgba(52,211,153,0.25)]', pill: 'bg-emerald-400/15 text-emerald-300', word: 'Done', accent: 'before:bg-emerald-400' },
  attention: { orb: 'border border-red-400/60 bg-red-500/15 text-red-200', pill: 'bg-red-400/20 text-red-200', word: 'Needs attention', accent: 'before:bg-red-400' },
}

/** The two agents that are not a stage in the line: Operations (keeps the record) and Notification (tells a
 *  person when they are needed). Shown under the progress panel as two clear cards. */
export function SupportStrip({ support, onSelect }: { support: SupportAgent[]; onSelect?: (agent: SupportAgent) => void }) {
  if (!support.length) return null
  return (
    <section className="mt-10" aria-label="Support agents">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-[0.16em] text-white/50">Behind the scenes</h3>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {support.map((s) => {
          const Icon = ICON[s.key]
          const tone = TONE[s.state]
          return (
            <div
              key={s.key}
              role={onSelect ? 'button' : undefined}
              tabIndex={onSelect ? 0 : undefined}
              aria-label={onSelect ? `Open ${s.name} details` : undefined}
              onClick={onSelect ? () => onSelect(s) : undefined}
              onKeyDown={onSelect ? (e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onSelect(s)) : undefined}
              className={clsx(
                'group relative flex items-start gap-3.5 overflow-hidden rounded-2xl border border-white/10 bg-linear-to-br from-white/8 to-white/2 p-4 pl-5 shadow-[0_4px_16px_rgba(0,0,0,0.2)] before:absolute before:inset-y-0 before:left-0 before:w-1',
                tone.accent,
                onSelect && 'cursor-pointer transition-[transform,background-color] duration-200 hover:-translate-y-0.5 hover:bg-white/8 motion-reduce:hover:translate-y-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-300/70',
              )}
            >
              <span className={clsx('flex h-11 w-11 shrink-0 items-center justify-center rounded-full', tone.orb)}>
                <Icon size={20} strokeWidth={1.9} />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
                  <span className="text-base font-semibold text-white">{s.name.replace(' Agent', '')}</span>
                  <span className={clsx('rounded-full px-2.5 py-0.5 text-xs font-semibold', tone.pill)}>{tone.word}</span>
                </div>
                <p className="mt-1 text-sm leading-snug text-slate-400">{s.label}</p>
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}
