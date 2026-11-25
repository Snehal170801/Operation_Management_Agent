import { Link } from 'react-router-dom'
import { CheckCircle2, TriangleAlert } from 'lucide-react'
import clsx from 'clsx'
import { Card } from '@/components/ui/Card'
import { QueryState } from '@/components/ui/QueryState'
import { timeAgo, parseUtc, useNow } from '@/lib/time'
import { Countdown } from './Countdown'
import { useMyWork } from './hooks'
import type { HandledItem, WorkItem, WorkQueue } from './types'

function Item({ item, now }: { item: WorkItem; now: number }) {
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3.5">
      <span
        aria-label={item.urgent ? 'Urgent' : undefined}
        className={clsx('h-2.5 w-2.5 shrink-0 rounded-full', item.urgent ? 'bg-danger' : 'bg-amber-400')}
      />
      <div className="min-w-0 flex-1">
        <p className="break-words text-sm font-semibold text-title">{item.title}</p>
        <p className="mt-0.5 break-words text-sm text-muted">{item.detail}</p>
        {item.note && (
          <p className="mt-1.5 flex items-start gap-1.5 text-xs text-amber-900">
            <TriangleAlert size={14} className="mt-px shrink-0" /> {item.note}
          </p>
        )}
        {item.since && <p className="mt-1 text-xs tabular-nums text-muted/80">Waiting {timeAgo(parseUtc(item.since), now).replace(' ago', '')}</p>}
        {item.since && item.escalates_at && <Countdown since={item.since} escalatesAt={item.escalates_at} now={now} />}
      </div>
      <Link
        to={item.link}
        className="inline-flex h-9 shrink-0 items-center rounded-lg bg-brand px-3.5 text-sm font-semibold text-white hover:opacity-90"
      >
        {item.action}
      </Link>
    </li>
  )
}

function Handled({ items, now }: { items: HandledItem[]; now: number }) {
  if (items.length === 0) return null
  return (
    <div className="border-t border-line bg-[#fafafc] px-5 py-3">
      <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">Recently handled</h3>
      <ul className="flex flex-col gap-1.5">
        {items.map((h) => (
          <li key={h.id} className="flex items-start gap-2 text-xs">
            <CheckCircle2 size={14} className="mt-px shrink-0 text-emerald-600" />
            <span className="min-w-0 flex-1 text-muted">
              <span className="font-medium text-title">{h.what}</span> · {h.title} · by {h.by}
            </span>
            <Link to={h.link} className="shrink-0 text-brand-ink hover:underline">
              {timeAgo(parseUtc(h.at), now)}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}

function Queue({ queue, now }: { queue: WorkQueue; now: number }) {
  const n = queue.items.length
  return (
    <Card title={queue.title} action={n ? `${n} waiting` : 'All clear'} bodyClassName="p-0">
      {n === 0 ? (
        <p className="flex items-center gap-2 px-5 py-6 text-sm text-emerald-700">
          <CheckCircle2 size={18} /> {queue.empty}
        </p>
      ) : (
        <ul className="divide-y divide-line">
          {queue.items.map((item) => (
            <Item key={item.id} item={item} now={now} />
          ))}
        </ul>
      )}
      <Handled items={queue.handled ?? []} now={now} />
    </Card>
  )
}

/** Each person's own home: only what their department is allowed to do, and what is waiting on them right now. */
export function MyWorkPage() {
  const work = useMyWork()
  const now = useNow()
  const data = work.data
  return (
    <div className="flex w-full flex-col gap-5">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="page-title">My work</h1>
        {data && (
          <span
            className={clsx(
              'rounded-full px-3 py-1 text-xs font-semibold',
              data.total ? 'bg-amber-100 text-amber-900' : 'bg-emerald-100 text-emerald-800',
            )}
          >
            {data.total ? `${data.total} waiting on you` : 'All clear'}
          </span>
        )}
      </div>

      <QueryState variant="cards" isLoading={work.isLoading} error={work.error} isEmpty={!!data && data.queues.length === 0} emptyMessage="Nothing is assigned to your role.">
        {data && (
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            {data.queues.map((q) => (
              <Queue key={q.key} queue={q} now={now} />
            ))}
          </div>
        )}
      </QueryState>
    </div>
  )
}
