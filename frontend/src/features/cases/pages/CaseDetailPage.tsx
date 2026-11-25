import { Link, useParams } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import { Card } from '@/components/ui/Card'
import { QueryState } from '@/components/ui/QueryState'
import { ApiError } from '@/lib/api-client'
import { eventLabel } from '@/lib/caseFlow'
import { formatDate, formatDateTime, humanize } from '@/lib/format'
import { UrgentBadge } from '../components/UrgentBadge'
import { CaseViewers } from '@/features/presence/CaseViewers'
import { usePurchaseRequest } from '@/features/purchase-requests/hooks'
import { CaseOperations } from '../components/CaseOperations'
import { DocumentStatusBanner } from '../components/DocumentStatusBanner'
import { useCase, useCaseEvents } from '../hooks'

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-muted">{label}</dt>
      <dd className="text-title">{children}</dd>
    </>
  )
}

/** The case is asked for first. A wrong link (or someone else's case, which the server also answers with "not found") gets one clear
 * page instead of empty panels, and none of the other requests are made for it. */
export function CaseDetailPage() {
  const { caseId = '' } = useParams()
  const caseQuery = useCase(caseId)
  const missing = caseQuery.error instanceof ApiError && (caseQuery.error.status === 404 || caseQuery.error.status === 422)
  if (missing) return <NoCaseFound caseId={caseId} />
  if (caseQuery.isLoading) {
    return (
      <div className="flex w-full max-w-5xl flex-col">
        <h1 className="page-title pb-4">Case</h1>
        <Card title="Case">
          <QueryState variant="detail" rows={5} isLoading error={null}>{null}</QueryState>
        </Card>
      </div>
    )
  }
  return <CaseDetail caseId={caseId} caseQuery={caseQuery} />
}

function NoCaseFound({ caseId }: { caseId: string }) {
  return (
    <div className="flex w-full max-w-5xl flex-col" role="alert">
      <Link to="/cases" className="mb-1 inline-flex items-center gap-1.5 text-sm font-medium text-brand-ink hover:underline">
        <ArrowLeft size={16} /> All cases
      </Link>
      <h1 className="page-title pb-4">No case found</h1>
      <Card>
        <p className="text-sm text-title">There is no case with this link. It may have been typed wrongly, or you may not have access to it.</p>
        <p className="mt-2 break-all text-xs text-muted">{caseId}</p>
        <Link to="/cases" className="mt-4 inline-block text-sm font-medium text-brand-ink hover:underline">
          Go to all cases
        </Link>
      </Card>
    </div>
  )
}

function CaseDetail({ caseId, caseQuery }: { caseId: string; caseQuery: ReturnType<typeof useCase> }) {
  const purchase = usePurchaseRequest(caseId)
  const events = useCaseEvents(caseId)

  return (
    <div className="flex w-full max-w-5xl flex-col">
      <Link to="/cases" className="mb-1 inline-flex items-center gap-1.5 text-sm font-medium text-brand-ink hover:underline">
        <ArrowLeft size={16} /> All cases
      </Link>
      <h1 className="page-title pb-4 tabular-nums">{caseQuery.data?.case_number ?? caseId}</h1>
      <CaseViewers caseId={caseId} />
      <div className="mb-4 empty:hidden"><DocumentStatusBanner events={events.data} staff /></div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="Case">
          <QueryState variant="detail" rows={5} isLoading={caseQuery.isLoading} error={caseQuery.error}>
            {caseQuery.data && (
              <dl className="grid grid-cols-[7rem_1fr] items-center gap-y-3 text-sm">
                <Row label="Requester">{caseQuery.data.requester_id}</Row>
                <Row label="Stage"><Badge value={caseQuery.data.stage} /></Row>
                <Row label="Status"><Badge value={caseQuery.data.status} /></Row>
                <Row label="Created">{formatDateTime(caseQuery.data.created_at)}</Row>
                <Row label="Updated">{formatDateTime(caseQuery.data.updated_at)}</Row>
              </dl>
            )}
          </QueryState>
        </Card>

        <Card title="Purchase request">
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
      </div>

      <CaseOperations caseId={caseId} />

      <Card title="Timeline" className="mt-4">
        <QueryState variant="list" rows={3} isLoading={events.isLoading} error={events.error} isEmpty={!events.data?.length} emptyMessage="No events yet.">
          <ol className="flex flex-col gap-4 text-sm">
            {events.data?.filter((e) => !e.event_type.startsWith('step.')).map((e) => (
              <li key={e.event_id} className="border-l-2 border-brand-soft pl-4">
                <div className="font-medium text-title">{e.label ?? eventLabel(e.event_type)}</div>
                <div className="text-xs text-muted">
                  {e.agent_name ? `${humanize(e.agent_name)} · ` : ''}
                  {formatDateTime(e.created_at)}
                </div>
              </li>
            ))}
          </ol>
        </QueryState>
      </Card>
    </div>
  )
}
