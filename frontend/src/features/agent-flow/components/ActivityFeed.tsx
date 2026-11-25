import clsx from 'clsx'
import { Card } from '@/components/ui/Card'
import { parseUtc, timeAgo } from '@/lib/time'
import type { FlowActivity } from '../types'

const DOT: Record<FlowActivity['tone'], string> = {
  info: 'bg-brand',
  ok: 'bg-[#16A34A]',
  warn: 'bg-amber-500',
  bad: 'bg-danger',
}

/** The latest things the agents did, newest first. A new line fades in as it arrives. */
export function ActivityFeed({ items, now }: { items: FlowActivity[]; now: number }) {
  return (
    <Card title="Latest activity" action="What the agents just did" bodyClassName="p-0">
      {items.length === 0 ? (
        <p className="px-5 py-8 text-sm text-muted">Nothing has happened yet.</p>
      ) : (
        <ul className="divide-y divide-line">
          {items.map((item) => (
            // The id never changes, so only a genuinely new line mounts (and plays the fade-in).
            <li key={item.id} className="dash-fade-in flex items-center gap-3 px-5 py-3">
              <span className={clsx('h-2.5 w-2.5 shrink-0 rounded-full', DOT[item.tone])} />
              <span className="min-w-0 flex-1 text-sm">
                <span className="font-semibold text-title">{item.agent}</span>
                <span className="text-muted"> · {item.text}</span>
              </span>
              <span className="shrink-0 text-xs tabular-nums text-muted">{timeAgo(parseUtc(item.at), now)}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}
