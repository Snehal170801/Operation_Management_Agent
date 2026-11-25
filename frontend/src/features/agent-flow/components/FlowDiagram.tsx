import type { ReactNode } from 'react'
import { AlertTriangle, Check, Minus, X } from 'lucide-react'
import clsx from 'clsx'
import { AnimatePresence, MotionConfig, motion } from 'motion/react'
import { AGENT_ICON, DOT, LEGEND, ORB, ORB_STYLE, PILL_STYLE, RING, STATE_STYLE } from '../agentStyle'
import type { AgentNode, AgentState } from '../types'

const SPRING = { type: 'spring', stiffness: 380, damping: 22 } as const

const CORNER: Partial<Record<AgentState, { Icon: typeof Check; tone: string }>> = {
  done: { Icon: Check, tone: 'bg-white text-[#15803d]' },
  needs_person: { Icon: AlertTriangle, tone: 'bg-red-500 text-white' },
  failed: { Icon: X, tone: 'bg-white text-red-600' },
  stopped: { Icon: X, tone: 'bg-white text-slate-700' },
  skipped: { Icon: Minus, tone: 'bg-slate-600 text-slate-300' },
}


/** Ring around a working agent: fills as "x of y" progresses, or spins while there is no count. */
function WorkRing({ progress }: { progress: AgentNode['progress'] }) {
  const r = RING / 2 - 3
  const circumference = 2 * Math.PI * r
  const fraction = progress && progress.total ? Math.min(1, progress.done / progress.total) : null
  const common = { cx: RING / 2, cy: RING / 2, r, fill: 'none', stroke: '#ff8a8b', strokeWidth: 3, strokeLinecap: 'round' } as const
  return (
    <svg aria-hidden width={RING} height={RING} viewBox={`0 0 ${RING} ${RING}`}
      className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2">
      <circle cx={RING / 2} cy={RING / 2} r={r} fill="none" stroke="rgba(255,255,255,0.14)" strokeWidth={3} />
      {fraction === null ? (
        <motion.circle {...common} strokeDasharray={`${circumference * 0.25} ${circumference}`} style={{ originX: '50%', originY: '50%' }}
          animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: 1.2, ease: 'linear' }} />
      ) : (
        <motion.circle {...common} strokeDasharray={circumference} transform={`rotate(-90 ${RING / 2} ${RING / 2})`} initial={false}
          animate={{ strokeDashoffset: circumference * (1 - Math.max(0.06, fraction)) }} transition={{ duration: 0.6, ease: 'easeOut' }} />
      )}
    </svg>
  )
}

export function Orb({ agent }: { agent: Pick<AgentNode, 'key' | 'state' | 'progress'> }) {
  const Icon = AGENT_ICON[agent.key]
  const corner = CORNER[agent.state]
  const working = agent.state === 'working'
  const pulse = working ? 'bg-brand/40' : agent.state === 'needs_person' ? 'bg-red-400/30' : agent.state === 'waiting' ? 'bg-amber-300/20' : ''
  return (
    <div className="relative flex shrink-0 items-center justify-center" style={{ width: RING, height: RING }}>
      {pulse && (
        <motion.span aria-hidden className={clsx('absolute rounded-full', pulse)} style={{ width: ORB, height: ORB }}
          animate={{ scale: [1, working ? 1.7 : 1.5], opacity: [0.8, 0] }}
          transition={{ repeat: Infinity, duration: working ? 1.5 : 2.4, ease: 'easeOut' }} />
      )}
      {working && <WorkRing progress={agent.progress} />}
      <motion.span
        className={clsx('relative flex items-center justify-center rounded-full transition-[background,box-shadow,color] duration-500', ORB_STYLE[agent.state])}
        style={{ width: ORB, height: ORB }}
        animate={working ? { scale: [1, 1.06, 1] } : { scale: 1 }}
        transition={working ? { repeat: Infinity, duration: 1.6, ease: 'easeInOut' } : SPRING}
      >
        <Icon size={32} strokeWidth={1.9} />
      </motion.span>
      <AnimatePresence initial={false}>
        {corner && (
          <motion.span key={agent.state} initial={{ scale: 0, rotate: -40 }} animate={{ scale: 1, rotate: 0 }} exit={{ scale: 0 }} transition={SPRING}
            className={clsx('absolute flex h-6 w-6 items-center justify-center rounded-full shadow ring-2 ring-[#14161c]', corner.tone)}
            style={{ right: (RING - ORB) / 2 - 3, bottom: (RING - ORB) / 2 - 3 }}>
            <corner.Icon size={14} strokeWidth={3} />
          </motion.span>
        )}
      </AnimatePresence>
    </div>
  )
}

/** Three bouncing dots: "thinking". */
export function Typing() {
  return (
    <span aria-hidden className="ml-1 inline-flex gap-0.5 align-middle">
      {[0, 1, 2].map((i) => (
        <motion.span key={i} className="h-1 w-1 rounded-full bg-brand" animate={{ y: [0, -3, 0], opacity: [0.4, 1, 0.4] }}
          transition={{ repeat: Infinity, duration: 0.9, delay: i * 0.15 }} />
      ))}
    </span>
  )
}

/** What the working agent is doing right now, in a speech bubble above it. */
function Bubble({ agent, edge }: { agent: AgentNode; edge: 'first' | 'last' | null }) {
  return (
    <AnimatePresence>
      {agent.state === 'working' && (
        <motion.div
          key="bubble"
          initial={{ opacity: 0, y: 8, scale: 0.9 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 6, scale: 0.9 }}
          transition={{ duration: 0.25 }}
          className={clsx(
            'absolute bottom-full z-10 mb-2 hidden w-max max-w-[220px] rounded-xl bg-white px-3.5 py-2 text-center text-xs font-semibold leading-snug text-slate-800 shadow-lg lg:block',
            edge === 'first' ? 'left-0' : edge === 'last' ? 'right-0' : 'left-1/2 -translate-x-1/2',
          )}
        >
          {agent.label}
          <Typing />
          {/* tail, pointing at the icon (always at the middle of the column) */}
          <span aria-hidden className="absolute top-full h-2 w-2 -translate-y-1 rotate-45 bg-white"
            style={{ left: edge === 'first' ? 'calc(50% - 4px)' : edge === 'last' ? undefined : 'calc(50% - 4px)', right: edge === 'last' ? 'calc(50% - 4px)' : undefined }} />
        </motion.div>
      )}
    </AnimatePresence>
  )
}

function Packets({ vertical }: { vertical: boolean }) {
  // Each packet rides in a box as long as the line and slides by a percentage of itself: a transform, so the
  // browser animates it on the graphics card without re-laying-out the page.
  return (
    <>
      {[0, 0.7].map((delay) => (
        <motion.span key={delay} aria-hidden
          className={vertical ? 'absolute top-0 h-full w-2.5' : 'absolute left-0 h-2.5 w-full'}
          style={vertical ? { left: -4.5 } : { top: -4.5 }}
          initial={vertical ? { y: '0%', opacity: 0 } : { x: '0%', opacity: 0 }}
          animate={vertical ? { y: '100%', opacity: [0, 1, 1, 0] } : { x: '100%', opacity: [0, 1, 1, 0] }}
          transition={{ repeat: Infinity, duration: 1.6, delay, ease: 'easeInOut' }}>
          <span className="block h-2.5 w-2.5 rounded-full bg-[#ff6b6c] shadow-[0_0_12px_4px_rgba(255,107,108,0.7)]" />
        </motion.span>
      ))}
    </>
  )
}

function Connector({ from, to, vertical }: { from: AgentState; to: AgentState; vertical: boolean }) {
  const flowing = to === 'working' && from === 'done'
  const filled = from === 'done' || from === 'skipped'
  const dashed = from === 'skipped'
  return (
    <span aria-hidden className={clsx('absolute', dashed ? 'bg-transparent' : 'bg-white/10', vertical ? 'w-0.5 lg:hidden' : 'hidden h-0.5 lg:block')}
      style={vertical
        ? { left: RING / 2 - 1, top: RING + 2, bottom: -2 }
        : { top: RING / 2 - 1, left: `calc(50% + ${RING / 2 + 4}px)`, right: `calc(-50% + ${RING / 2 + 4}px)` }}>
      {dashed && <span className={clsx('absolute inset-0 border-white/15', vertical ? 'border-l-2 border-dashed' : 'border-t-2 border-dashed')} />}
      {!dashed && (
        <motion.span className="absolute inset-0 bg-[linear-gradient(90deg,#22c55e,#4ade80)]" initial={false}
          animate={vertical ? { scaleY: filled ? 1 : 0 } : { scaleX: filled ? 1 : 0 }} transition={{ duration: 0.9, ease: 'easeInOut' }}
          style={{ transformOrigin: vertical ? 'top' : 'left' }} />
      )}
      {flowing && <Packets vertical={vertical} />}
    </span>
  )
}

interface FlowDiagramProps {
  agents: AgentNode[]
  /** Shown across the top of the stage (the case, and what is happening). */
  header?: ReactNode
  /** Hide the colour key (e.g. when something else already explains it). */
  hideLegend?: boolean
  /** Shown under the agents, above the colour key (e.g. the journey bar). */
  footer?: ReactNode
  /** When given, each agent can be clicked (or tabbed to) to open its details. */
  onSelect?: (agent: AgentNode) => void
}

/** The stage: the agents as glowing characters on a dark canvas, joined by lines that light up as work is handed on.
 *  A row on wide screens, a vertical timeline on narrow ones. Movement is limited to transforms and opacity, and
 *  stops entirely for people who prefer reduced motion. */
export function FlowDiagram({ agents, header, hideLegend, footer, onSelect }: FlowDiagramProps) {
  // Spotlight: while someone is working (or needs a person), the agents that are finished or not started
  // step back a little so the eye goes to where the work is. Hover or focus brings one back.
  const spotlight = agents.some((a) => a.state === 'working' || a.state === 'needs_person')
  return (
    <MotionConfig reducedMotion="user">
      <div className="relative overflow-hidden rounded-2xl bg-[#14161c] text-white shadow-[0_8px_30px_rgba(20,22,28,0.25)]">
        {/* soft glows and a faint dot grid */}
        <div aria-hidden className="pointer-events-none absolute inset-0 bg-[radial-gradient(600px_220px_at_12%_0%,rgba(234,77,78,0.22),transparent),radial-gradient(500px_240px_at_95%_100%,rgba(34,197,94,0.10),transparent)]" />
        <div aria-hidden className="pointer-events-none absolute inset-0 opacity-70 [background-image:radial-gradient(rgba(255,255,255,0.07)_1px,transparent_1px)] [background-size:22px_22px]" />

        <div className="relative px-6 pb-8 pt-7 sm:px-10 lg:flex lg:min-h-[640px] lg:flex-col">
          {header && <div className="mb-6">{header}</div>}

          <ol className="flex flex-col lg:my-auto lg:grid lg:grid-cols-7 lg:pt-20 lg:pb-6" aria-label="Agent pipeline">
            {agents.map((agent, i) => {
              const last = i === agents.length - 1
              const label = STATE_STYLE[agent.state].word
              return (
                <li key={agent.key} aria-label={`${agent.name}: ${label}. ${agent.label}`}
                  className={clsx(
                    'relative flex gap-4 pb-8 transition-opacity duration-500 last:pb-0 hover:opacity-100 focus-within:opacity-100 lg:flex-col lg:items-center lg:gap-5 lg:pb-0 lg:text-center',
                    spotlight && (agent.state === 'done' || agent.state === 'pending' || agent.state === 'skipped') ? 'opacity-55' : 'opacity-100',
                  )}>
                  {!last && (
                    <>
                      <Connector from={agent.state} to={agents[i + 1].state} vertical />
                      <Connector from={agent.state} to={agents[i + 1].state} vertical={false} />
                    </>
                  )}

                  <div className="relative">
                    <Bubble agent={agent} edge={i === 0 ? 'first' : last ? 'last' : null} />
                    <Orb agent={agent} />
                  </div>

                  <div className="min-w-0 flex-1 lg:flex-none lg:px-1.5">
                    <div className="text-base font-semibold text-white">
                      {onSelect ? (
                        // The name is the real button; its ::after stretches over the whole agent so all of it is clickable.
                        <button
                          type="button"
                          onClick={() => onSelect(agent)}
                          aria-label={`Open ${agent.name} details`}
                          className="cursor-pointer font-semibold after:absolute after:inset-0 after:rounded-xl after:transition-colors hover:after:bg-white/5 focus-visible:outline-none focus-visible:after:ring-2 focus-visible:after:ring-rose-300/70"
                        >
                          {agent.name.replace(' Agent', '')}
                        </button>
                      ) : (
                        agent.name.replace(' Agent', '')
                      )}
                    </div>
                    <div>
                      <motion.span key={agent.state} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45, ease: 'easeOut' }}
                        className={clsx('mt-1.5 inline-flex rounded-full px-3 py-1 text-xs font-semibold', PILL_STYLE[agent.state])}>
                        {label}
                      </motion.span>
                    </div>
                    <motion.p key={agent.label} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.5, ease: 'easeOut' }}
                      className="mt-2 text-sm leading-snug text-slate-400">
                      {agent.label}
                    </motion.p>
                    {agent.progress && agent.state === 'working' && (
                      <div className="mt-2">
                        <div className="mx-auto h-1 w-full max-w-[110px] overflow-hidden rounded-full bg-white/10">
                          <motion.div className="h-full rounded-full bg-brand" initial={false}
                            animate={{ width: `${Math.max(6, (agent.progress.done / Math.max(1, agent.progress.total)) * 100)}%` }}
                            transition={{ duration: 0.5 }} />
                        </div>
                        <p className="mt-1 text-xs font-medium tabular-nums text-rose-200">{agent.progress.done} of {agent.progress.total}</p>
                      </div>
                    )}
                    {agent.seconds != null && agent.seconds > 0 && agent.state !== 'working' && (
                      <p className="mt-1.5 text-xs tabular-nums text-slate-500">took {agent.seconds.toFixed(1)} s</p>
                    )}
                  </div>
                </li>
              )
            })}
          </ol>

          {footer}

          {!hideLegend && (
            <ul className="mt-10 flex flex-wrap gap-x-6 gap-y-2 border-t border-white/10 pt-5 text-xs text-slate-400" aria-label="Legend">
              {LEGEND.map((state) => (
                <li key={state} className="flex items-center gap-2">
                  <span className={clsx('h-2 w-2 rounded-full', DOT[state])} />
                  {STATE_STYLE[state].word}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </MotionConfig>
  )
}
