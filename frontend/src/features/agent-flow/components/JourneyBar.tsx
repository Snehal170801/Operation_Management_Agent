import { Check, TriangleAlert, X } from 'lucide-react'
import clsx from 'clsx'
import type { AgentNode, AgentState } from '../types'

/** The dot under each agent: filled and ticked when finished, glowing while it works, hollow until its turn. */
const DOT: Record<AgentState, string> = {
  done: 'bg-emerald-400 text-[#0b3b24] shadow-[0_0_14px_rgba(52,211,153,0.6)]',
  skipped: 'bg-emerald-400/40 text-emerald-100',
  working: 'bg-brand text-white shadow-[0_0_16px_rgba(255,107,108,0.8)] motion-safe:animate-pulse',
  waiting: 'bg-amber-400 text-amber-950 shadow-[0_0_14px_rgba(251,191,36,0.6)]',
  needs_person: 'bg-red-500 text-white shadow-[0_0_14px_rgba(248,113,113,0.7)]',
  failed: 'bg-red-600 text-white shadow-[0_0_14px_rgba(248,113,113,0.7)]',
  stopped: 'bg-slate-500 text-white',
  pending: 'border-2 border-white/20 bg-[#14161c] text-white/40',
}

/** A circular gauge: the percentage in the middle, a coloured arc that fills as steps finish. */
function Ring({ percent, tone, glow }: { percent: number; tone: string; glow: string }) {
  const size = 68
  const r = size / 2 - 6
  const c = 2 * Math.PI * r
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className={clsx('-rotate-90', glow)} aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(255,255,255,0.1)" strokeWidth={6} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={tone}
          strokeWidth={6}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - percent / 100)}
          className="transition-[stroke-dashoffset] duration-700 ease-out motion-reduce:transition-none"
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center text-lg font-semibold tabular-nums text-white">
        {percent}
        <span className="text-[10px] text-slate-400">%</span>
      </div>
    </div>
  )
}

/** The whole journey as one bar that runs under the agents: a dot sits right under each agent (the same columns as
 *  the row above), and the bar fills from the first dot up to the one being worked on. */
export function JourneyBar({ agents }: { agents: AgentNode[] }) {
  const total = agents.length
  const finished = agents.filter((a) => a.state === 'done' || a.state === 'skipped').length
  const currentAgent = agents.find((a) => a.state === 'working' || a.state === 'waiting' || a.state === 'needs_person' || a.state === 'failed')
  const current = currentAgent ? agents.indexOf(currentAgent) : -1
  const stopped = agents.some((a) => a.state === 'stopped')
  const percent = Math.round((finished / Math.max(1, total)) * 100)

  const complete = finished === total
  const stuck = currentAgent?.state === 'needs_person' || currentAgent?.state === 'failed'
  const label = complete ? 'Complete' : current >= 0 ? `Step ${current + 1} of ${total}` : stopped ? 'Stopped' : `${finished} of ${total} done`
  const detail = complete
    ? `All ${total} steps are done`
    : currentAgent
      ? `${stuck ? 'Needs attention' : 'Now'}: ${currentAgent.name.replace(' Agent', '')}`
      : stopped
        ? 'This request was stopped'
        : 'Waiting to start'

  // The bar runs from the middle of the first column to the middle of the last, so each dot sits under its agent.
  const edge = 50 / total
  const fill = complete ? 1 : Math.min(1, finished / Math.max(1, total - 1))
  const ringTone = stuck ? '#f87171' : complete ? '#34d399' : '#ff6b6c'
  const ringGlow = stuck ? 'drop-shadow-[0_0_8px_rgba(248,113,113,0.55)]' : complete ? 'drop-shadow-[0_0_8px_rgba(52,211,153,0.55)]' : 'drop-shadow-[0_0_8px_rgba(255,107,108,0.55)]'
  const fillTone = stuck ? 'from-red-500 to-red-300' : complete ? 'from-emerald-500 to-emerald-300' : 'from-emerald-500 via-emerald-400 to-brand'

  return (
    <section aria-label="Progress" className="mt-12 border-t border-white/10 pt-6">
      <div className="flex items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-4">
          <Ring percent={percent} tone={ringTone} glow={ringGlow} />
          <div className="min-w-0">
            <div className="text-xl font-semibold leading-tight text-white">{label}</div>
            <p className="mt-1 text-sm text-slate-400">{detail}</p>
          </div>
        </div>
        <span
          className={clsx(
            'hidden shrink-0 rounded-full px-3.5 py-1.5 text-sm font-semibold tabular-nums sm:inline-flex',
            complete ? 'bg-emerald-400/15 text-emerald-300' : stuck ? 'bg-red-400/15 text-red-300' : 'bg-white/10 text-slate-200',
          )}
        >
          {finished} of {total} steps done
        </span>
      </div>

      <div className="relative mt-7 h-8" role="img" aria-label={`${label}, ${percent} percent`}>
        <div className="absolute top-1/2 h-2.5 -translate-y-1/2 rounded-full bg-white/10" style={{ left: `${edge}%`, right: `${edge}%` }}>
          <div
            className={clsx('h-full rounded-full bg-linear-to-r shadow-[0_0_14px_rgba(52,211,153,0.5)] transition-[width] duration-700 ease-out motion-reduce:transition-none', fillTone)}
            style={{ width: `${fill * 100}%` }}
          />
        </div>
        <ol className="absolute inset-0 grid" style={{ gridTemplateColumns: `repeat(${total}, minmax(0, 1fr))` }}>
          {agents.map((a, i) => (
            <li key={a.key} className="flex items-center justify-center" title={`${a.name}: ${a.label}`}>
              <span className={clsx('flex h-8 w-8 items-center justify-center rounded-full text-xs font-bold transition-colors duration-500', DOT[a.state])}>
                {a.state === 'done' || a.state === 'skipped' ? (
                  <Check size={16} strokeWidth={3.5} />
                ) : a.state === 'needs_person' ? (
                  <TriangleAlert size={15} strokeWidth={2.5} />
                ) : a.state === 'failed' || a.state === 'stopped' ? (
                  <X size={15} strokeWidth={3} />
                ) : (
                  i + 1
                )}
              </span>
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}
