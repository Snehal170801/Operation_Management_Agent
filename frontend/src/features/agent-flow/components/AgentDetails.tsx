import clsx from 'clsx'
import { Card } from '@/components/ui/Card'
import { Table, Td, Tr } from '@/components/ui/Table'
import { formatDateTime } from '@/lib/format'
import { STATE_STYLE } from '../agentStyle'
import type { AgentNode } from '../types'

/** Staff only: the numbers and any error behind each agent. */
export function AgentDetails({ agents }: { agents: AgentNode[] }) {
  return (
    <Card title="Agent details" action="Staff view" bodyClassName="flex min-h-0 flex-col p-0">
      <Table headers={['Agent', 'State', 'What it is doing', 'Runs', 'Time taken', 'Last finished', 'Problem']}>
        {agents.map((a) => (
          <Tr key={a.key}>
            <Td first className="font-medium">{a.name}</Td>
            <Td>
              <span className={clsx('inline-flex rounded-full px-2.5 py-1 text-[11px] font-semibold', STATE_STYLE[a.state].pill)}>
                {STATE_STYLE[a.state].word}
              </span>
            </Td>
            <Td className="max-w-[280px]">
              <span className="block truncate" title={a.label}>{a.label}</span>
              {a.detail && <span className="block truncate text-xs text-muted" title={a.detail}>{a.detail}</span>}
            </Td>
            <Td className="tabular-nums">{a.runs || '—'}</Td>
            <Td className="tabular-nums">{a.seconds ? `${a.seconds.toFixed(1)} s` : '—'}</Td>
            <Td className="whitespace-nowrap">{a.finished_at ? formatDateTime(a.finished_at) : '—'}</Td>
            <Td className="max-w-[260px]">
              {a.error ? <span className="block truncate text-danger" title={a.error}>{a.error}</span> : <span className="text-muted">—</span>}
            </Td>
          </Tr>
        ))}
      </Table>
    </Card>
  )
}
