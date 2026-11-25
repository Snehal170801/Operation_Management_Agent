import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge } from '@/components/ui/Badge'
import { Card } from '@/components/ui/Card'
import { QueryState } from '@/components/ui/QueryState'
import { Table, Td, Tr } from '@/components/ui/Table'
import { useAuth } from '@/features/auth/AuthContext'
import { formatDateTime } from '@/lib/format'
import { ApprovalActions } from '../components/ApprovalActions'
import { ApprovalReviewCard } from '../components/ApprovalReviewCard'
import { PriceChangeCard } from '../components/PriceChangeCard'
import { useApprovals } from '../hooks'

const FILTERS = [
  { value: 'pending', label: 'Waiting for me' },
  { value: '', label: 'All' },
] as const

export function ApprovalsPage() {
  const { can } = useAuth()
  const [status, setStatus] = useState<string>('pending')
  const { data, isLoading, error } = useApprovals(status || undefined)
  const canDecide = can('approvals:write')

  return (
    <div className="flex w-full flex-col xl:h-full">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 pb-4">
        <div>
          <h1 className="page-title">Approvals</h1>
          <p className="text-sm text-muted">
            Routine orders are approved automatically. These need a person because something was unusual.
          </p>
        </div>
        <div className="flex w-full rounded-xl border border-line bg-white p-1 sm:w-auto">
          {FILTERS.map((f) => (
            <button
              key={f.label}
              type="button"
              onClick={() => setStatus(f.value)}
              className={
                'h-10 flex-1 rounded-lg px-4 text-sm font-medium sm:h-8 sm:flex-none ' +
                (status === f.value ? 'bg-brand-soft text-brand-ink' : 'text-muted hover:bg-brand-tint')
              }
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {status === 'pending' && (
        <QueryState variant="detail" rows={4} isLoading={isLoading} error={error} isEmpty={!data?.length} emptyMessage="Nothing is waiting for approval.">
          <div className="flex flex-col gap-5">
            {data?.map((a) => (
              a.approval_type === 'price_change' ? (
                <PriceChangeCard key={a.approval_id} approvalId={a.approval_id} />
              ) : (
                <ApprovalReviewCard key={a.approval_id} approvalId={a.approval_id} />
              )
            ))}
          </div>
        </QueryState>
      )}

      {status !== 'pending' && (
      <Card className="flex-1" bodyClassName="flex min-h-0 flex-col p-0">
        <QueryState
          variant="table" columns={6}
          isLoading={isLoading}
          error={error}
          isEmpty={!data?.length}
          emptyMessage={status === 'pending' ? 'Nothing is waiting for approval.' : 'No approvals yet.'}
        >
          <Table headers={['Case', 'Why a person is needed', 'Status', 'Requested', 'Decided by', '']}>
            {data?.map((a) => (
              <Tr key={a.approval_id}>
                <Td first>
                  <Link to={`/cases/${a.case_id}`} className="tabular-nums text-xs font-medium text-brand-ink hover:underline">
                    {a.case_number ?? a.case_id.slice(0, 8)}
                  </Link>
                </Td>
                <Td className="max-w-[360px]">
                  {a.reasons.length ? (
                    <ul className="list-disc py-2 pl-4 text-xs">
                      {a.reasons.map((r) => (
                        <li key={r}>{r}</li>
                      ))}
                    </ul>
                  ) : (
                    <span className="text-muted">Routine</span>
                  )}
                </Td>
                <Td>
                  <Badge value={a.status} />
                </Td>
                <Td>{formatDateTime(a.created_at)}</Td>
                <Td>{a.decided_by ?? '—'}</Td>
                <Td>{a.status === 'pending' && canDecide ? <ApprovalActions approvalId={a.approval_id} /> : null}</Td>
              </Tr>
            ))}
          </Table>
        </QueryState>
      </Card>
      )}
    </div>
  )
}
