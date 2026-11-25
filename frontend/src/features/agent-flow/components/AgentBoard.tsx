import { Link } from 'react-router-dom'
import clsx from 'clsx'
import { AnimatePresence, MotionConfig, motion } from 'motion/react'
import { LiveStatus } from '@/components/ui/LiveStatus'
import { QueryState } from '@/components/ui/QueryState'
import { parseUtc, timeAgo, useNow } from '@/lib/time'
import { DOT, LEGEND, PILL_STYLE, RING, STATE_STYLE } from '../agentStyle'
import { useAgentBoard } from '../hooks'
import type { AgentState, BoardAgent, BoardFeedItem } from '../types'
import { Orb, Typing } from './FlowDiagram'

/** The one word that best describes an agent right now. */
function columnState(a: BoardAgent): { state: AgentState; word: string } {
  if (a.needs_person) return { state: 'needs_person', word: `${a.needs_person} blocked` }
  if (a.working) return { state: 'working', word: `${a.working} working` }
  if (a.waiting) return { state: 'waiting', word: `${a.waiting} waiting` }
  return { state: 'pending', word: 'Idle' }
}

const CASE_CHIP: Partial<Record<AgentState, string>> = {
  working: 'border-brand/40 bg-brand/15',
  needs_person: 'border-red-400/50 bg-red-500/15',
  failed: 'border-red-400/50 bg-red-500/15',
  waiting: 'border-amber-400/30 bg-amber-400/10',
}

/** What the working agent is doing right now, in a speech bubble above it (wide screens). */
function Bubble({ text, edge }: { text: string | null; edge: 'first' | 'last' | null }) {
  return (
    <AnimatePresence>
      {text && (
        <motion.div
          key="bubble"
          initial={{ opacity: 0, y: 8, scale: 0.9 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 6, scale: 0.9 }}
          transition={{ duration: 0.25 }}
          className={clsx(
            'absolute bottom-full z-10 mb-2 hidden w-max max-w-[200px] rounded-xl bg-white px-3.5 py-2 text-center text-xs font-semibold leading-snug text-slate-800 shadow-lg lg:block',
            edge === 'first' ? 'left-0' : edge === 'last' ? 'right-0' : 'left-1/2 -translate-x-1/2',
          )}
        >
          {text}
          <Typing />
          <span
            aria-hidden
            className="absolute top-full h-2 w-2 -translate-y-1 rotate-45 bg-white"
            style={{ left: edge === 'last' ? undefined : 'calc(50% - 4px)', right: edge === 'last' ? 'calc(50% - 4px)' : undefined }}
          />
        </motion.div>
      )}
    </AnimatePresence>
  )
}

/** The line joining two agents: green where work is moving, faint where nothing is. */
function Connector({ lit, vertical }: { lit: boolean; vertical: boolean }) {
  return (
    <span
      aria-hidden
      className={clsx('absolute', lit ? 'bg-[linear-gradient(90deg,#22c55e,#4ade80)]' : 'bg-white/10', vertical ? 'w-0.5 lg:hidden' : 'hidden h-0.5 lg:block')}
      style={
        vertical
          ? { left: RING / 2 - 1, top: RING + 2, bottom: -2 }
          : { top: RING / 2 - 1, left: `calc(50% + ${RING / 2 + 4}px)`, right: `calc(-50% + ${RING / 2 + 4}px)` }
      }
    />
  )
}

function Column({ agent, index, count, spotlight }: { agent: BoardAgent; index: number; count: number; spotlight: boolean }) {
  const { state, word } = columnState(agent)
  const last = index === count - 1
  const idle = state === 'pending'
  return (
    <li
      className={clsx(
        'relative flex gap-4 pb-8 transition-opacity duration-500 last:pb-0 hover:opacity-100 focus-within:opacity-100 lg:flex-col lg:items-center lg:gap-5 lg:pb-0 lg:text-center',
        spotlight && idle ? 'opacity-55' : 'opacity-100',
      )}
    >
      {!last && (
        <>
          <Connector lit={!idle} vertical />
          <Connector lit={!idle} vertical={false} />
        </>
      )}

      <div className="relative">
        <Bubble text={agent.now_doing} edge={index === 0 ? 'first' : last ? 'last' : null} />
        <Orb agent={{ key: agent.key, state, progress: null }} />
      </div>

      <div className="min-w-0 flex-1 lg:w-full lg:flex-none lg:px-1.5">
        <div className="text-base font-semibold text-white">{agent.name.replace(' Agent', '')}</div>
        <span className={clsx('mt-1.5 inline-flex rounded-full px-3 py-1 text-xs font-semibold', PILL_STYLE[state])}>{word}</span>
        <p className="mt-2 text-sm leading-snug text-slate-400 lg:hidden">{agent.now_doing ?? agent.role}</p>
        <p className="mt-2 hidden text-sm leading-snug text-slate-400 lg:block">{agent.role}</p>

        {agent.cases.length > 0 && (
          <ul className="mt-4 flex flex-col gap-1.5 text-left">
            <AnimatePresence initial={false}>
              {agent.cases.map((c) => (
                <motion.li key={c.case_id} layout initial={{ opacity: 0, scale: 0.94 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.94 }} transition={{ duration: 0.2 }}>
                  <Link
                    to={`/agent-flow?case=${c.case_id}`}
                    className={clsx('block rounded-xl border px-2.5 py-2 transition-colors hover:bg-white/10', CASE_CHIP[c.state] ?? 'border-white/10 bg-white/5')}
                  >
                    {c.case_number && <span className="block text-[10px] font-semibold tabular-nums tracking-wide text-rose-200">{c.case_number}</span>}
                    <span className="block truncate text-xs font-semibold text-white" title={c.items_summary ?? ''}>
                      {c.items_summary ?? 'Request'}
                    </span>
                    <span className="block truncate text-[11px] text-slate-400" title={c.label}>
                      {c.progress ? `${c.label} (${c.progress.done}/${c.progress.total})` : c.label}
                    </span>
                    {c.requester && <span className="block truncate text-[10px] text-slate-500">{c.requester}</span>}
                  </Link>
                </motion.li>
              ))}
            </AnimatePresence>
            {agent.more > 0 && <li className="text-center text-[11px] text-slate-400">+ {agent.more} more</li>}
          </ul>
        )}
      </div>
    </li>
  )
}

const FEED_DOT = { info: 'bg-brand', ok: 'bg-emerald-400', warn: 'bg-amber-400', bad: 'bg-red-400' } as const

/** What the agents have been doing, across every case. New lines slide in at the top. */
function LiveFeed({ items, now }: { items: BoardFeedItem[]; now: number }) {
  return (
    <div className="mt-10 border-t border-white/10 pt-5">
      <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-white/60">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400 motion-reduce:animate-none" /> Live activity
      </div>
      {items.length === 0 ? (
        <p className="py-2 text-sm text-white/40">Quiet right now. New activity will appear here as it happens.</p>
      ) : (
        <ul className="grid grid-cols-1 gap-x-8 lg:grid-cols-2">
          <AnimatePresence initial={false}>
            {items.slice(0, 8).map((f) => (
              <motion.li key={f.id} layout initial={{ opacity: 0, x: -12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.25 }}>
                <Link to={`/agent-flow?case=${f.case_id}`} className="flex items-start gap-3 rounded-xl px-2 py-2 hover:bg-white/5">
                  <span className={clsx('mt-1.5 h-2 w-2 shrink-0 rounded-full', FEED_DOT[f.tone])} />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm leading-snug text-slate-200">
                      <b className="font-semibold text-white">{f.agent}</b> · {f.text}
                    </span>
                    <span className="mt-0.5 block text-xs tabular-nums text-slate-500">
                      <span className="font-semibold text-rose-200/80">{f.case_number ?? 'Request'}</span> · {timeAgo(parseUtc(f.at), now)}
                    </span>
                  </span>
                </Link>
              </motion.li>
            ))}
          </AnimatePresence>
        </ul>
      )}
    </div>
  )
}

/** Staff overview, built like the one-case stage: the same glowing agents on the same dark canvas, but each one
 *  carries how many cases it holds, and the cases themselves hang underneath it. */
export function AgentBoard() {
  const board = useAgentBoard(true)
  const now = useNow()
  const data = board.data
  // Same spotlight as the one-case stage: idle agents step back while others are busy.
  const spotlight = !!data?.agents.some((a) => a.working || a.needs_person)
  return (
    <MotionConfig reducedMotion="user">
      <QueryState variant="cards" isLoading={board.isLoading} error={board.error}>
        {data && (
          <div className="relative overflow-hidden rounded-2xl bg-[#14161c] text-white shadow-[0_8px_30px_rgba(20,22,28,0.25)]">
            <div
              aria-hidden
              className="pointer-events-none absolute inset-0 bg-[radial-gradient(600px_220px_at_12%_0%,rgba(234,77,78,0.22),transparent),radial-gradient(500px_240px_at_95%_100%,rgba(34,197,94,0.10),transparent)]"
            />
            <div
              aria-hidden
              className="pointer-events-none absolute inset-0 opacity-70 [background-image:radial-gradient(rgba(255,255,255,0.07)_1px,transparent_1px)] [background-size:22px_22px]"
            />

            <div className="relative px-6 pb-8 pt-7 sm:px-10">
              <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold uppercase tracking-[0.18em] text-white/50">Live board</span>
                    <span
                      className={clsx(
                        'rounded-full px-3 py-1 text-xs font-semibold',
                        data.needs_person ? 'bg-amber-400/20 text-amber-200' : 'bg-emerald-400/20 text-emerald-200',
                      )}
                    >
                      {data.needs_person ? `${data.needs_person} need a person` : 'All running smoothly'}
                    </span>
                  </div>
                  <h2 className="mt-3 text-2xl font-semibold leading-snug text-white sm:text-3xl">
                    {data.open_cases} open case{data.open_cases === 1 ? '' : 's'} · {data.working_now} being worked on right now
                  </h2>
                  <p className="mt-1.5 text-sm text-slate-400">Click a case to watch its agents at work.</p>
                </div>
                <LiveStatus dark minimal updatedAt={board.dataUpdatedAt} fetching={board.isFetching} failed={board.isError && !!data} now={now} />
              </div>

              <ol className="flex flex-col lg:grid lg:grid-cols-7 lg:pb-2 lg:pt-20" aria-label="Agents and their cases">
                {data.agents.map((a, i) => (
                  <Column key={a.key} agent={a} index={i} count={data.agents.length} spotlight={spotlight} />
                ))}
              </ol>

              <LiveFeed items={data.feed} now={now} />

              <ul className="mt-8 flex flex-wrap gap-x-6 gap-y-2 border-t border-white/10 pt-5 text-xs text-slate-400" aria-label="Legend">
                {LEGEND.map((state) => (
                  <li key={state} className="flex items-center gap-2">
                    <span className={clsx('h-2 w-2 rounded-full', DOT[state])} />
                    {STATE_STYLE[state].word}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </QueryState>
    </MotionConfig>
  )
}
