import { Link, useParams } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { Card } from '@/components/ui/Card'
import { QueryState } from '@/components/ui/QueryState'
import { describeCase, eventLabel } from '@/lib/caseFlow'
import { formatDate, formatDateTime } from '@/lib/format'
import { UrgentBadge } from '@/features/cases/components/UrgentBadge'
import { useCase, useCaseEvents } from '@/features/cases/hooks'
import { usePurchaseRequest } from '@/features/purchase-requests/hooks'
import { DocumentStatusBanner } from '@/features/cases/components/DocumentStatusBanner'
import { FlowTracker } from '../components/FlowTracker'
import { ChangeCard } from '@/features/case-changes/ChangeCard'
import { ReceiptCard } from '../components/ReceiptCard'

const POLL_MS = 10_000

/** Read-only view for the requester: the request, a live step tracker and a plain-language timeline. */
export function RequestDetailPage() {
  const { caseId = '' } = useParams()
  // Keep the tracker live while the request is still being worked on.
  const caseQuery = useCase(caseId, POLL_MS)
  const isOpen = caseQuery.data?.status === 'open'
  const events = useCaseEvents(caseId, isOpen ? POLL_MS : false)
  const purchase = usePurchaseRequest(caseId)

  const flow = caseQuery.data ? describeCase(caseQuery.data.stage, caseQuery.data.status) : null

  return (
    <div className="flex w-full max-w-5xl flex-col">
      <Link
        to="/requests"
        className="mb-1 inline-flex items-center gap-1.5 text-sm font-medium text-brand-ink hover:underline"
      >
        <ArrowLeft size={16} /> My requests
      </Link>
      <h1 className="page-title pb-4">Your request{caseQuery.data?.case_number ? ` · ${caseQuery.data.case_number}` : ''}</h1>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="Progress" action={isOpen ? 'Updating live' : undefined}>
          <QueryState variant="detail" rows={4} isLoading={caseQuery.isLoading} error={caseQuery.error}>
            {flow && (
              <div className="flex flex-col gap-4">
                <p className="rounded-xl bg-brand-tint px-4 py-3 text-sm font-medium text-title">{flow.headline}</p>
                <DocumentStatusBanner events={events.data} staff={false} />
                <FlowTracker states={flow.states} />
              </div>
            )}
          </QueryState>
        </Card>

        <div className="flex flex-col gap-4">
          <ReceiptCard caseId={caseId} />
          <ChangeCard caseId={caseId} />
          <Card title="What you asked for">
            <QueryState variant="detail" rows={3} isLoading={purchase.isLoading} error={purchase.error}>
              {purchase.data && (
                <div className="text-sm">
                  {purchase.data.urgent || purchase.data.needed_by ? (
                  <p className="mb-2">
                    {purchase.data.urgent && <UrgentBadge neededBy={purchase.data.needed_by} />}
                    {!purchase.data.urgent && purchase.data.needed_by && <span className="text-xs text-muted">Needed by {formatDate(purchase.data.needed_by)}</span>}
                  </p>
                ) : null}
                <p className="mb-3 italic text-muted">“{purchase.data.raw_request}”</p>
                  <ul className="divide-y divide-line rounded-xl border border-line">
                    {purchase.data.items.map((i) => (
                      <li key={i.description} className="flex justify-between px-4 py-2.5">
                        <span className="text-title">{i.description}</span>
                        <span className="font-semibold text-brand-ink">× {i.quantity}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </QueryState>
          </Card>

          <Card title="What the agents have done">
            <QueryState
              variant="list" rows={3}
              isLoading={events.isLoading}
              error={events.error}
              isEmpty={!events.data?.length}
              emptyMessage="Nothing yet."
            >
              <ol className="flex flex-col gap-4 text-sm">
                {events.data?.map((e) => (
                  <li key={e.event_id} className="border-l-2 border-brand-soft pl-4">
                    <div className="font-medium text-title">{eventLabel(e.event_type)}</div>
                    <div className="text-xs text-muted">{formatDateTime(e.created_at)}</div>
                  </li>
                ))}
              </ol>
            </QueryState>
          </Card>
        </div>
      </div>
    </div>
  )
}
