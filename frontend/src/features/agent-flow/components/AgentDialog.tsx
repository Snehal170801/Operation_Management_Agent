import { useEffect } from 'react'
import { AlertTriangle, X } from 'lucide-react'
import clsx from 'clsx'
import { formatDate, formatDateTime } from '@/lib/format'
import { parseUtc, timeAgo } from '@/lib/time'
import { BellRing, ClipboardList, type LucideIcon } from 'lucide-react'
import { AGENT_ICON, STATE_STYLE } from '../agentStyle'
import type { AgentInfo, AgentNode, FlowActivity } from '../types'
import { InfoSections } from './InfoSections'

/** What the box shows: a stage agent, or one of the two support agents (which are not a stage in the line). */
export type DialogAgent = Omit<AgentNode, 'key'> & { key: string }

const SUPPORT_ICON: Record<string, LucideIcon> = { operations: ClipboardList, notification: BellRing }

const DOT: Record<FlowActivity['tone'], string> = {
  info: 'bg-brand',
  ok: 'bg-[#16A34A]',
  warn: 'bg-amber-500',
  bad: 'bg-danger',
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-brand-tint/60 px-4 py-3">
      <dd className="text-base font-semibold tabular-nums text-title">{value}</dd>
      <dt className="mt-0.5 text-xs text-muted">{label}</dt>
    </div>
  )
}

/** One agent in full: what it is doing, its numbers, and what it has done on this case. */
export function AgentDialog({
  agent,
  activity,
  info,
  infoLoading,
  expectedDelivery,
  staff,
  now,
  when = 'ago',
  onClose,
}: {
  agent: DialogAgent
  activity: FlowActivity[]
  /** The full account of what this agent did (in a replay: as it was at the moment shown). */
  info?: AgentInfo | null
  infoLoading?: boolean
  /** The date the goods are due; shown on the Delivery agent. */
  expectedDelivery?: string | null
  staff: boolean
  now: number
  /** 'ago' ("5 min ago") on the live page; 'time' (the clock time) in a replay, where "ago" would be misleading. */
  when?: 'ago' | 'time'
  onClose: () => void
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const Icon = SUPPORT_ICON[agent.key] ?? AGENT_ICON[agent.key as keyof typeof AGENT_ICON]
  const style = STATE_STYLE[agent.state]
  const short = agent.name.replace(' Agent', '')
  const mine = activity.filter((a) => a.agent === agent.name || a.agent === short)
  const progress = agent.progress

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/45 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-label={`${agent.name} details`}
        className="flex max-h-[92dvh] w-full max-w-[780px] flex-col overflow-hidden rounded-2xl border border-line bg-white shadow-[0_8px_40px_rgba(0,0,0,0.18)]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* who it is, and what it is up to */}
        <div className="flex items-start gap-4 border-b border-line bg-brand-tint/50 p-6">
          <span className={clsx('flex h-14 w-14 shrink-0 items-center justify-center rounded-full', style.orb)}>
            <Icon size={26} strokeWidth={1.9} />
          </span>
          <div className="min-w-0 flex-1">
            <h3 className="text-lg font-semibold leading-tight text-title">{agent.name}</h3>
            <p className="mt-0.5 text-sm text-muted">{agent.role}</p>
            <span className={clsx('mt-2 inline-flex rounded-full px-2.5 py-1 text-[11px] font-semibold', style.pill)}>{style.word}</span>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white text-brand-ink hover:bg-brand-soft"
          >
            <X size={18} />
          </button>
        </div>

        <div className="flex flex-col gap-5 overflow-y-auto p-6">
          <section>
            <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">Right now</h4>
            <p className="mt-1.5 text-[15px] font-medium leading-snug text-title">{agent.label}</p>
            {progress && progress.total > 0 && (
              <div className="mt-3">
                <div className="h-2 overflow-hidden rounded-full bg-line">
                  <div
                    className="h-full rounded-full bg-brand transition-[width] duration-500"
                    style={{ width: `${Math.max(6, (progress.done / progress.total) * 100)}%` }}
                  />
                </div>
                <p className="mt-1 text-xs tabular-nums text-muted">
                  {progress.done} of {progress.total}
                  {progress.text ? ` · ${progress.text}` : ''}
                </p>
              </div>
            )}
          </section>

          {staff && agent.error && (
            <p className="flex items-start gap-2 rounded-xl bg-danger-soft px-4 py-3 text-sm text-danger">
              <AlertTriangle size={16} className="mt-0.5 shrink-0" />
              <span className="min-w-0 break-words">{agent.error}</span>
            </p>
          )}

          <dl className="grid grid-cols-2 gap-3">
            <Stat label="Steps run" value={agent.runs ? String(agent.runs) : '—'} />
            <Stat label="Time taken" value={agent.seconds ? `${agent.seconds.toFixed(1)} s` : '—'} />
            <Stat label="Started" value={agent.started_at ? formatDateTime(agent.started_at) : '—'} />
            <Stat label="Finished" value={agent.finished_at ? formatDateTime(agent.finished_at) : '—'} />
            {agent.key === 'delivery' && expectedDelivery && <Stat label="Expected by" value={formatDate(expectedDelivery)} />}
          </dl>

          {staff && agent.detail && (
            <section>
              <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">Details</h4>
              <p className="mt-1.5 break-words text-sm leading-relaxed text-title">{agent.detail}</p>
            </section>
          )}

          {info && <InfoSections sections={info.sections} />}
          {!info && infoLoading && <p className="text-sm text-muted">Loading the details…</p>}
          {info && info.sections.length === 0 && (
            <p className="rounded-xl bg-brand-tint px-4 py-3 text-sm text-muted">This agent hasn't started on this request yet, so there is nothing to show.</p>
          )}

          {!info && !infoLoading && (
          <section>
            <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">What it did on this request</h4>
            {mine.length === 0 ? (
              <p className="mt-1.5 text-sm text-muted">Nothing yet.</p>
            ) : (
              <ul className="mt-2 divide-y divide-line rounded-xl border border-line">
                {mine.map((item) => (
                  <li key={item.id} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                    <span className={clsx('h-2.5 w-2.5 shrink-0 rounded-full', DOT[item.tone])} />
                    <span className="min-w-0 flex-1 text-title">{item.text}</span>
                    <span className="shrink-0 text-xs tabular-nums text-muted">{when === 'time' ? formatDateTime(item.at) : timeAgo(parseUtc(item.at), now)}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
          )}
        </div>
      </div>
    </div>
  )
}
