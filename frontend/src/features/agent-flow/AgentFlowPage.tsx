import { useCallback, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ChevronDown, Play, TriangleAlert } from 'lucide-react'
import clsx from 'clsx'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { LiveStatus } from '@/components/ui/LiveStatus'
import { QueryState } from '@/components/ui/QueryState'
import { useAuth } from '@/features/auth/AuthContext'
import { formatDate, formatDateTime, humanize } from '@/lib/format'
import { parseUtc, useNow } from '@/lib/time'
import { ActivityFeed } from './components/ActivityFeed'
import { AgentBoard } from './components/AgentBoard'
import { ReplayPlayer } from './components/ReplayPlayer'
import { AgentDetails } from './components/AgentDetails'
import { AgentDialog } from './components/AgentDialog'
import { RequestCard } from './components/RequestCard'
import { JourneyBar } from './components/JourneyBar'
import { NeedsAttention } from './components/NeedsAttention'
import { StoryLine } from './components/StoryLine'
import { SupportStrip } from './components/SupportStrip'
import { FlowDiagram } from './components/FlowDiagram'
import { useAgentFlow, useAgentInfo, useFlowCases } from './hooks'
import type { AgentFlowCase, AgentFlowState, FlowOutcome, SupportAgent } from './types'
import type { DialogAgent } from './components/AgentDialog'

const OUTCOME_CHIP: Record<FlowOutcome, { text: string; tone: string }> = {
  active: { text: 'In progress', tone: 'bg-brand/25 text-rose-100' },
  needs_person: { text: 'Needs a person', tone: 'bg-amber-400/20 text-amber-200' },
  completed: { text: 'Complete', tone: 'bg-emerald-400/20 text-emerald-200' },
  fulfilled: { text: 'Fulfilled from stock', tone: 'bg-emerald-400/20 text-emerald-200' },
  rejected: { text: 'Not approved', tone: 'bg-red-400/20 text-red-200' },
  cancelled: { text: 'Cancelled', tone: 'bg-slate-400/20 text-slate-200' },
  merged: { text: 'Combined with another request', tone: 'bg-sky-400/20 text-sky-200' },
}

function seconds(total: number): string {
  return total >= 60 ? `${(total / 60).toFixed(1)} min` : `${total.toFixed(1)} s`
}

/** How long the case has been going (open) or took (finished), from when the first agent started. */
function elapsed(flow: AgentFlowState, now: number): string {
  const starts = flow.agents.map((a) => a.started_at).filter((v): v is string => !!v).map(parseUtc)
  if (!starts.length) return '—'
  const begin = Math.min(...starts)
  const ends = flow.agents.map((a) => a.finished_at).filter((v): v is string => !!v).map(parseUtc)
  const end = flow.status === 'closed' && ends.length ? Math.max(...ends) : now
  const mins = Math.max(0, (end - begin) / 60000)
  return mins < 1 ? `${Math.round(mins * 60)} s` : mins < 60 ? `${mins.toFixed(1)} min` : mins < 1440 ? `${(mins / 60).toFixed(1)} h` : `${(mins / 1440).toFixed(1)} days`
}

/** The four key numbers in one slim strip (instead of four boxes). */
function SummaryStrip({ items }: { items: { label: string; value: string }[] }) {
  return (
    <dl className="grid grid-cols-2 divide-line rounded-2xl border border-card-border bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)] sm:grid-cols-4 sm:divide-x">
      {items.map((item) => (
        <div key={item.label} className="px-5 py-4">
          <dd className="text-xl font-semibold leading-tight tabular-nums text-title">{item.value}</dd>
          <dt className="mt-0.5 text-xs text-muted">{item.label}</dt>
        </div>
      ))}
    </dl>
  )
}

/** The agent whose box is open: a stage agent, or one of the two support agents shaped to fit the same box. */
const SUPPORT_STATE: Record<SupportAgent['state'], DialogAgent['state']> = { idle: 'pending', active: 'working', done: 'done', attention: 'needs_person' }

function dialogAgent(flow: AgentFlowState, key: string): DialogAgent | undefined {
  const stage = flow.agents.find((a) => a.key === key)
  if (stage) return stage
  const support = flow.support.find((s) => s.key === key)
  if (!support) return undefined
  return {
    key: support.key, name: support.name, role: support.role, state: SUPPORT_STATE[support.state], label: support.label, progress: null,
    started_at: null, finished_at: null, seconds: null, runs: 0, detail: null, error: null,
  }
}

function caseLabel(c: AgentFlowCase, staff: boolean): string {
  const what = c.items_summary ?? 'Request'
  return `${c.case_number ? `${c.case_number} · ` : ''}${staff && c.requester ? `${c.requester} · ` : ''}${what} · ${c.active ? humanize(c.stage) : 'Finished'}`
}

/** One page for everyone: a requester sees the agents working on their request, staff on any case. */
export function AgentFlowPage() {
  const { can } = useAuth()
  const staff = can('cases:read_all')
  const [params, setParams] = useSearchParams()

  const cases = useFlowCases()
  const list = cases.data ?? []

  // Which case to show. A case the person picked (kept in the address) always wins. Otherwise the page
  // follows the newest request: it starts on the one most recently being worked on, and switches only when a
  // brand-new active request appears. It never jumps just because some other case was updated.
  // Staff can switch between the all-cases board and a single case; picking a case on the board opens it.
  const [view, setView] = useState<'board' | 'case'>('board')
  const [followed, setFollowed] = useState<string>()
  const [seen, setSeen] = useState('')
  const ids = list.map((c) => c.case_id).join(',')
  if (ids !== seen) {
    setSeen(ids)
    const known = new Set(seen ? seen.split(',') : [])
    const fresh = seen ? list.find((c) => !known.has(c.case_id) && c.active) : list[0]
    if (fresh) setFollowed(fresh.case_id)
  }
  const byId = (id?: string | null) => list.find((c) => c.case_id.toLowerCase() === id?.toLowerCase())
  const selected = byId(params.get('case')) ?? byId(followed) ?? list[0]

  const showBoard = staff && view === 'board' && !params.get('case')
  const [replaying, setReplaying] = useState(false)
  const [showDetails, setShowDetails] = useState(false)
  const [openAgent, setOpenAgent] = useState<string>()
  const closeReplay = useCallback(() => setReplaying(false), [])
  const flow = useAgentFlow(showBoard ? undefined : selected?.case_id)
  const now = useNow()
  const agentInfo = useAgentInfo(showBoard ? undefined : selected?.case_id, openAgent, flow.data?.status === 'closed')

  return (
    <div className="flex w-full flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="page-title">Agent Flow</h1>
        {staff && (
          <div role="tablist" className="flex gap-1 rounded-xl border border-line bg-white p-1">
            {(
              [
                ['board', 'Live board'],
                ['case', 'One case'],
              ] as const
            ).map(([id, label]) => {
              const active = showBoard ? id === 'board' : id === 'case'
              return (
                <button
                  key={id}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => {
                    setView(id)
                    if (id === 'board') setParams({}, { replace: true })
                  }}
                  className={clsx(
                    'inline-flex h-9 items-center rounded-lg px-4 text-sm font-medium transition-colors',
                    active ? 'bg-brand-soft text-brand-ink' : 'text-muted hover:bg-brand-tint',
                  )}
                >
                  {label}
                </button>
              )
            })}
          </div>
        )}
      </div>

      {showBoard ? (
        <>
          <NeedsAttention />
          <AgentBoard />
        </>
      ) : (
      <QueryState
        variant="detail"
        rows={4}
        isLoading={cases.isLoading}
        error={cases.error}
        isEmpty={!list.length}
        emptyMessage={staff ? 'There are no cases yet.' : "You haven't submitted a request yet."}
      >
        <div className="flex flex-wrap items-center gap-3">
          <select
            aria-label={staff ? 'Choose a case' : 'Choose your request'}
            value={selected?.case_id}
            onChange={(e) => {
              setReplaying(false)
              setOpenAgent(undefined)
              setParams({ case: e.target.value }, { replace: true })
            }}
            className="h-11 min-w-[240px] max-w-full flex-1 rounded-xl border border-line bg-white px-3 text-sm font-medium text-title shadow-[0_1px_2px_rgba(15,23,42,0.04)] focus:border-brand focus:outline-none sm:max-w-xl sm:flex-none"
          >
            {list.map((c) => (
              <option key={c.case_id} value={c.case_id}>
                {caseLabel(c, staff)}
              </option>
            ))}
          </select>
          {selected && <Badge value={selected.status} />}

          <div className="ml-auto flex flex-wrap gap-2">
            {!replaying && selected && (
              <Button onClick={() => setReplaying(true)}>
                <Play size={16} /> Play replay
              </Button>
            )}
            {staff && selected ? (
              <Link to={`/cases/${selected.case_id}`}>
                <Button variant="secondary">Open case</Button>
              </Link>
            ) : (
              <Link to="/requests">
                <Button variant="secondary">My requests</Button>
              </Link>
            )}
          </div>
        </div>

        {replaying && selected ? (
          <ReplayPlayer key={selected.case_id} caseId={selected.case_id} autoPlay onClose={closeReplay} />
        ) : (
          <QueryState variant="detail" rows={5} isLoading={flow.isLoading} error={flow.error} isEmpty={!flow.data}>
            {flow.data && (
              <FlowDiagram
                agents={flow.data.agents}
                onSelect={(a) => setOpenAgent(a.key)}
                footer={<><JourneyBar agents={flow.data.agents} /><SupportStrip support={flow.data.support} onSelect={(s) => setOpenAgent(s.key)} /></>}
                header={
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-semibold uppercase tracking-[0.18em] text-white/50">
                          {flow.data.case_number ?? 'Request'}
                        </span>
                        <span className={clsx('rounded-full px-3 py-1 text-xs font-semibold', OUTCOME_CHIP[flow.data.outcome].tone)}>
                          {OUTCOME_CHIP[flow.data.outcome].text}
                        </span>
                      </div>
                      <StoryLine agents={flow.data.agents} headline={flow.data.headline} nextStep={flow.data.next_step} />
                    </div>
                    {flow.data.status !== 'closed' ? (
                      <LiveStatus dark updatedAt={flow.dataUpdatedAt} fetching={flow.isFetching} failed={flow.isError && !!flow.data} now={now} />
                    ) : (
                      <span className="text-xs text-white/50">Finished</span>
                    )}
                  </div>
                }
              />
            )}
          </QueryState>
        )}

        {flow.data && !replaying && openAgent && dialogAgent(flow.data, openAgent) && (
          <AgentDialog
            agent={dialogAgent(flow.data, openAgent)!}
            info={agentInfo.data}
            infoLoading={agentInfo.isLoading}
            activity={flow.data.activity}
            expectedDelivery={flow.data.expected_delivery}
            staff={staff}
            now={now}
            onClose={() => setOpenAgent(undefined)}
          />
        )}

        {flow.data && !replaying && (
          <SummaryStrip
            items={[
              { label: 'Working now', value: String(flow.data.agents.filter((a) => a.state === 'working').length) },
              { label: 'Steps completed', value: String(flow.data.agents.reduce((n, a) => n + a.runs, 0)) },
              { label: 'Agent time', value: seconds(flow.data.agents.reduce((n, a) => n + (a.seconds ?? 0), 0)) },
              { label: flow.data.status === 'closed' ? 'Took in total' : 'Running for', value: elapsed(flow.data, now) },
            ]}
          />
        )}

        {flow.data && !replaying && (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <ActivityFeed items={flow.data.activity} now={now} />
            </div>
            <div className="flex flex-col gap-3">
              <RequestCard
                request={flow.data.request}
                rows={[
                  ...(flow.data.expected_delivery ? ([['Expected delivery', formatDate(flow.data.expected_delivery)]] as [string, string][]) : []),
                  ['Stage', humanize(flow.data.stage)],
                  ['Last update', selected ? formatDateTime(selected.updated_at) : '—'],
                ]}
              />
              {flow.data.needs_person && (
                <p className="flex items-start gap-2 rounded-xl bg-amber-50 px-3 py-2.5 text-xs text-amber-900">
                  <TriangleAlert size={15} className="mt-0.5 shrink-0" /> A person is needed to move this on.
                </p>
              )}
            </div>
          </div>
        )}

        {staff && flow.data && (
          <div className="flex flex-col gap-3">
            <button
              type="button"
              onClick={() => setShowDetails((v) => !v)}
              aria-expanded={showDetails}
              className="inline-flex items-center gap-1.5 self-start text-sm font-medium text-brand-ink hover:underline"
            >
              <ChevronDown size={16} className={clsx('transition-transform', showDetails && 'rotate-180')} />
              {showDetails ? 'Hide agent details' : 'Show agent details'}
            </button>
            {showDetails && <AgentDetails agents={flow.data.agents} />}
          </div>
        )}
      </QueryState>
      )}
    </div>
  )
}
