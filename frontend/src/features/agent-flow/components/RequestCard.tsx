import { Card } from '@/components/ui/Card'
import { formatDateTime } from '@/lib/format'
import type { RequestDetails } from '../types'

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2.5 text-sm">
      <dt className="shrink-0 text-muted">{label}</dt>
      <dd className="min-w-0 break-words text-right font-medium text-title">{children}</dd>
    </div>
  )
}

/** The request itself: what the person asked for in their own words, what the Purchase agent made of it,
 *  and the facts around it. `rows` adds case facts that belong beside it (stage, last update...). */
export function RequestCard({ request, rows = [] }: { request: RequestDetails | null | undefined; rows?: [string, string][] }) {
  return (
    <Card title="The request" action={request?.submitted_at ? `Sent ${formatDateTime(request.submitted_at)}` : undefined} bodyClassName="flex flex-col gap-4 p-5">
      {request ? (
        <>
          <section>
            <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">In their words</h4>
            <blockquote className="mt-1.5 whitespace-pre-wrap break-words rounded-xl bg-brand-tint px-4 py-3 text-sm leading-relaxed text-title">
              {request.raw_text}
            </blockquote>
          </section>

          {request.items.length > 0 && (
            <section>
              <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">What was understood</h4>
              <ul className="mt-1.5 divide-y divide-line rounded-xl border border-line">
                {request.items.map((item, i) => (
                  <li key={i} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                    <span className="min-w-0 flex-1 break-words font-medium text-title">{item.description}</span>
                    <span className="shrink-0 rounded-full bg-brand-soft px-2.5 py-0.5 text-xs font-semibold tabular-nums text-brand-ink">× {item.quantity}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <dl className="divide-y divide-line">
            {request.requested_by && <Row label="Requested by">{request.requested_by}</Row>}
            {request.cost_center && <Row label="Cost center">{request.cost_center}</Row>}
            {rows.map(([label, value]) => (
              <Row key={label} label={label}>{value}</Row>
            ))}
          </dl>
        </>
      ) : (
        <>
          <p className="text-sm text-muted">The request text isn't available for this case.</p>
          <dl className="divide-y divide-line">
            {rows.map(([label, value]) => (
              <Row key={label} label={label}>{value}</Row>
            ))}
          </dl>
        </>
      )}
    </Card>
  )
}
