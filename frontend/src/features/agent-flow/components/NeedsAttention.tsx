import { Link } from 'react-router-dom'
import { TriangleAlert } from 'lucide-react'
import { useAuth } from '@/features/auth/AuthContext'
import { useAgentBoard } from '../hooks'
import type { BoardCase } from '../types'

const MAX_SHOWN = 5

/** Cases that are stuck until a person acts, with a button straight to where they can do it. Shown above the
 *  live board and hidden when nothing needs anyone. It deliberately links to the Approvals page / the case
 *  instead of approving in one click: an approval sends an order to a supplier, so it should be read first. */
export function NeedsAttention() {
  const { can } = useAuth()
  const board = useAgentBoard(true) // same query as the board below, so no extra requests
  const seen = new Set<string>()
  const stuck: { agent: string; agentKey: string; c: BoardCase }[] = []
  for (const agent of board.data?.agents ?? []) {
    for (const c of agent.cases) {
      if ((c.state === 'needs_person' || c.state === 'failed') && !seen.has(c.case_id)) {
        seen.add(c.case_id)
        stuck.push({ agent: agent.name.replace(' Agent', ''), agentKey: agent.key, c })
      }
    }
  }
  if (!stuck.length) return null

  return (
    <section aria-label="Needs a person" className="rounded-2xl border border-amber-200 bg-amber-50 p-4 sm:p-5">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-amber-900">
        <TriangleAlert size={16} />
        {stuck.length} {stuck.length === 1 ? 'case needs' : 'cases need'} a person
      </h2>
      <ul className="mt-3 flex flex-col gap-2">
        {stuck.slice(0, MAX_SHOWN).map(({ agent, agentKey, c }) => (
          <li key={c.case_id} className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl bg-white px-4 py-3 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2 text-sm">
                {c.case_number && <span className="font-semibold tabular-nums text-title">{c.case_number}</span>}
                <span className="truncate text-muted">{c.items_summary ?? 'Request'}</span>
                {c.requester && <span className="truncate text-xs text-muted">· {c.requester}</span>}
              </div>
              <p className="mt-0.5 text-sm text-amber-900">
                <b className="font-semibold">{agent}</b> · {c.label}
              </p>
            </div>
            <div className="flex shrink-0 gap-2">
              <Link
                to={`/agent-flow?case=${c.case_id}`}
                className="inline-flex h-9 items-center rounded-lg border border-line px-3 text-sm font-medium text-title hover:bg-brand-tint"
              >
                Watch
              </Link>
              <Link
                to={agentKey === 'approval' && can('approvals:read') ? '/approvals' : `/cases/${c.case_id}`}
                className="inline-flex h-9 items-center rounded-lg bg-brand px-3 text-sm font-semibold text-white hover:opacity-90"
              >
                {agentKey === 'approval' ? 'Review & decide' : 'Open case'}
              </Link>
            </div>
          </li>
        ))}
      </ul>
      {stuck.length > MAX_SHOWN && <p className="mt-2 text-xs text-amber-900">+ {stuck.length - MAX_SHOWN} more on the board below</p>}
    </section>
  )
}
