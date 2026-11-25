import { useState } from 'react'
import { AlertTriangle, FileText, PackageCheck, RefreshCw } from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { NoteModal } from '@/components/ui/NoteModal'
import { QueryState } from '@/components/ui/QueryState'
import { useApprovals } from '@/features/approvals/hooks'
import { ApprovalActions } from '@/features/approvals/components/ApprovalActions'
import { useAuth } from '@/features/auth/AuthContext'
import { useConfirmDelivery, useDelivery, useShortClose } from '@/features/delivery/hooks'
import { ReceiveModal } from '@/features/delivery/components/ReceiveModal'
import { useDisputeHandled, useReceiptForStaff } from '@/features/delivery/receipt'
import { ChangeCard } from '@/features/case-changes/ChangeCard'
import { CombinePanel } from '@/features/case-changes/CombinePanel'
import { GoodsIssuePanel } from '@/features/goods-issues/GoodsIssuePanel'
import { api } from '@/lib/api-client'
import { useCaseDocuments } from '@/features/document-store/hooks'
import { useCase } from '../hooks'
import { PoDeskPanel } from '@/features/case-changes/PoDeskPanel'
import { useConfirmPurchaseOrder, useIssuePurchaseOrder, usePurchaseOrder } from '@/features/purchase-orders/hooks'
import { InvoiceCard } from '@/features/invoices/components/InvoiceCard'
import { AddQuoteModal } from '@/features/vendors/components/AddQuoteModal'
import { useQuotes, useRfqs } from '@/features/vendors/hooks'
import { formatAmount, formatDate, formatDateTime } from '@/lib/format'

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-muted">{label}</dt>
      <dd className="text-title">{children}</dd>
    </>
  )
}

/** Staff view of what the agents did on a case: suppliers and quotes, approval, order and delivery. */
export function CaseOperations({ caseId }: { caseId: string }) {
  const { can } = useAuth()
  return (
    <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
      {can('vendors:read') && <SupplierCard caseId={caseId} />}
      {can('approvals:read') && <ApprovalCard caseId={caseId} />}
      <PurchaseOrderCard caseId={caseId} />
      <DeliveryCard caseId={caseId} />
      <InvoiceCard caseId={caseId} />
      {can('cases:write') && <ChangeCard caseId={caseId} />}
      <CombinePanel caseId={caseId} />
      <DocumentsCard caseId={caseId} />
    </div>
  )
}

/** Printable copies for staff: the purchase order and a one-page summary of the request, offers, AI reasoning and decision. */
function DocumentsCard({ caseId }: { caseId: string }) {
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const stored = useCaseDocuments(caseId)

  async function open(file: 'purchase-order' | 'approval-summary') {
    setError(null)
    setBusy(file)
    const tab = window.open('', '_blank') // opened now, while the click still counts, and filled when the file arrives
    try {
      const blob = await api.blob(`/cases/${encodeURIComponent(caseId)}/documents/${file}.pdf`)
      const url = URL.createObjectURL(blob)
      if (tab) tab.location.href = url
      else window.location.assign(url)
      setTimeout(() => URL.revokeObjectURL(url), 5 * 60_000)
    } catch (e) {
      tab?.close()
      setError(e instanceof Error ? e.message : 'The document could not be made.')
    } finally {
      setBusy(null)
    }
  }

  return (
    <Card title="Documents" className="lg:col-span-2">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="secondary" onClick={() => open('purchase-order')} loading={busy === 'purchase-order'} disabled={busy !== null}>
          <FileText size={15} /> Purchase order (PDF)
        </Button>
        <Button variant="secondary" onClick={() => open('approval-summary')} loading={busy === 'approval-summary'} disabled={busy !== null}>
          <FileText size={15} /> Approval summary (PDF)
        </Button>
      </div>
      <p className="mt-2 text-xs text-muted">Opens in a new tab, ready to print or save. The purchase order exists once the order is placed.</p>
      {error && <p className="mt-2 text-sm text-danger">{error}</p>}
      {stored.data && stored.data.items.length > 0 && (
        <div className="mt-4">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Everything held for this case</h3>
          <ul className="mt-2 divide-y divide-line rounded-xl border border-line text-sm">
            {stored.data.items.map((d) => (
              <li key={d.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-4 py-2.5">
                <span className="min-w-0">
                  <span className="font-medium text-title">{d.title}</span>
                  <span className="ml-2 text-xs text-muted">{d.kind_label}{d.vendor ? ` · ${d.vendor}` : ''}{d.status ? ` · ${d.status}` : ''}</span>
                </span>
                <span className="whitespace-nowrap text-xs text-muted tabular-nums">{d.amount !== null ? `${formatAmount(d.amount)} · ` : ''}{d.at ? formatDateTime(d.at) : ''}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  )
}

function SupplierCard({ caseId }: { caseId: string }) {
  const { can } = useAuth()
  const rfqs = useRfqs(caseId)
  const quotes = useQuotes(caseId)
  const [adding, setAdding] = useState(false)
  const nothing = !rfqs.data?.length && !quotes.data?.length

  return (
    <Card
      title="Suppliers & quotes"
      className="lg:col-span-2"
      action={
        can('vendors:write') && !!rfqs.data?.length ? (
          <button type="button" onClick={() => setAdding(true)} className="font-medium text-brand-ink hover:underline">
            Add a quote by hand
          </button>
        ) : undefined
      }
    >
      <AddQuoteModal
        caseId={caseId}
        open={adding}
        suppliers={(rfqs.data ?? []).map((r) => ({ vendor_id: r.vendor_id, name: r.vendor_name }))}
        onClose={() => setAdding(false)}
      />
      <QueryState
        variant="list" rows={3}
        isLoading={rfqs.isLoading || quotes.isLoading}
        error={rfqs.error ?? quotes.error}
        isEmpty={nothing}
        emptyMessage="No quote requests yet. Quotes are requested automatically when stock is not enough."
      >
        <div className="flex flex-col gap-5 text-sm">
          {!!rfqs.data?.length && (
            <div>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Quote requests sent</h3>
              <ul className="divide-y divide-line rounded-xl border border-line">
                {rfqs.data.map((r) => (
                  <li key={r.rfq_id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5">
                    <span className="font-medium text-title">{r.vendor_name}</span>
                    <span className="text-xs text-muted">
                      {r.status === 'replied'
                        ? `Replied ${formatDateTime(r.replied_at)}`
                        : `Reply due ${formatDateTime(r.deadline_at)} · ${r.reminder_count} reminder(s)`}
                    </span>
                    <Badge value={r.status} />
                  </li>
                ))}
              </ul>
            </div>
          )}
          {!!quotes.data?.length && (
            <div>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Quotes received</h3>
              <ul className="divide-y divide-line rounded-xl border border-line">
                {quotes.data.map((q) => (
                  <li key={q.quote_id} className="grid grid-cols-2 gap-2 px-4 py-2.5 sm:grid-cols-4">
                    <span className="font-medium text-title">{q.vendor_name}</span>
                    <span>{formatAmount(q.price)}</span>
                    <span>{q.lead_time_days != null ? `${q.lead_time_days} days` : '—'}</span>
                    <span className="truncate text-muted" title={q.terms ?? undefined}>
                      {q.terms ?? '—'}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </QueryState>
    </Card>
  )
}

function ApprovalCard({ caseId }: { caseId: string }) {
  const { can } = useAuth()
  const approvals = useApprovals(undefined, caseId)
  const list = (approvals.data ?? []).filter((a) => a.status !== 'superseded')

  return (
    <Card title="Approval">
      <QueryState
        variant="list" rows={2}
        isLoading={approvals.isLoading}
        error={approvals.error}
        isEmpty={!list.length}
        emptyMessage="No approval needed yet."
      >
        <ul className="flex flex-col gap-4 text-sm">
          {list.map((a) => (
            <li key={a.approval_id} className="flex flex-col gap-2">
              <div className="flex items-center justify-between gap-2">
                <Badge value={a.status} />
                <span className="text-xs text-muted">{formatDateTime(a.decided_at ?? a.created_at)}</span>
              </div>
              {a.approval_type === 'price_change' && <p className="text-xs font-semibold text-amber-800">The supplier asked for a different price on the order</p>}
              {a.reasons.length > 0 ? (
                <ul className="list-disc pl-5 text-xs text-title">
                  {a.reasons.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-muted">Routine order - approved automatically by policy.</p>
              )}
              {a.decided_by && a.decided_by !== 'policy' && (
                <p className="text-xs text-muted">
                  By {a.decided_by}
                  {a.decision_note ? ` - “${a.decision_note}”` : ''}
                </p>
              )}
              {a.status === 'pending' && can('approvals:write') && <ApprovalActions approvalId={a.approval_id} kind={a.approval_type} />}
            </li>
          ))}
        </ul>
      </QueryState>
    </Card>
  )
}

function PurchaseOrderCard({ caseId }: { caseId: string }) {
  const { can } = useAuth()
  const po = usePurchaseOrder(caseId)
  const retry = useIssuePurchaseOrder(caseId)
  const confirm = useConfirmPurchaseOrder(caseId)
  const [confirming, setConfirming] = useState(false)
  const failed = po.data?.status === 'send_failed'
  const sent = po.data?.status === 'sent'
  const problem = sent ? po.data?.vendor_issue : null
  const overdue = sent && !po.data?.acknowledged_at && !!po.data?.confirm_escalated_at

  return (
    <Card title="Purchase order" action={po.data?.po_number}>
      <QueryState
        variant="detail" rows={4}
        isLoading={po.isLoading}
        error={po.error}
        isEmpty={!po.data}
        emptyMessage="No purchase order yet. One is created automatically once a vendor is approved."
      >
        {po.data && (
          <div className="flex flex-col gap-3">
            <dl className="grid grid-cols-[8rem_1fr] items-center gap-y-3 text-sm">
              <Row label="Vendor">{po.data.vendor_name}</Row>
              {po.data.tax_rate_pct && po.data.tax_amount !== null && po.data.total_with_tax !== null ? (
                <>
                  <Row label="Subtotal">{formatAmount(po.data.total_with_tax - po.data.tax_amount)}</Row>
                  <Row label={`Tax (${po.data.tax_rate_pct}%)`}>{formatAmount(po.data.tax_amount)}</Row>
                  <Row label="Total with tax">{formatAmount(po.data.total_with_tax)}</Row>
                </>
              ) : (
                <Row label="Total">{formatAmount(po.data.total_amount)}</Row>
              )}
              <Row label="Expected by">{formatDate(po.data.expected_delivery_date)}</Row>
              <Row label="Terms">{po.data.terms ?? '—'}</Row>
              <Row label="Email to vendor">
                <Badge value={po.data.status} />
              </Row>
              <Row label="Items">{po.data.items.map((i) => `${i.description} × ${i.quantity}`).join(', ')}</Row>
              {sent && (
                <Row label="Supplier confirmed?">
                  {po.data.acknowledged_at ? (
                    <span className="text-[#16A34A]">
                      Yes · {formatDateTime(po.data.acknowledged_at)}{po.data.acknowledged_by ? ` · ${po.data.acknowledged_by}` : ''}
                    </span>
                  ) : (
                    <span className={overdue ? 'text-danger' : 'text-muted'}>
                      {overdue ? 'No answer after reminders' : 'Waiting'}
                      {po.data.confirm_chase_count ? ` · asked ${po.data.confirm_chase_count} time(s)` : ''}
                    </span>
                  )}
                </Row>
              )}
            </dl>
            {can('po:manage') && po.data && <PoDeskPanel caseId={caseId} po={po.data} />}
            {(problem || overdue) && (
              <div className="flex flex-col gap-2 rounded-xl bg-danger-soft px-3 py-2.5 text-xs text-danger">
                <span className="flex items-start gap-2">
                  <AlertTriangle size={16} className="mt-0.5 shrink-0" />
                  <span>
                    {problem ? `The supplier replied and raised a problem: ${problem}. Read their reply and sort it out with them.` : 'The supplier has not confirmed the order after repeated reminders. Please contact them.'}
                  </span>
                </span>
                {can('po:manage') && (
                  <div>
                    <Button variant="secondary" onClick={() => setConfirming(true)}>
                      <PackageCheck size={16} /> {problem ? 'The problem is sorted out' : 'Mark as confirmed'}
                    </Button>
                  </div>
                )}
              </div>
            )}
            {sent && !po.data.acknowledged_at && !overdue && !problem && can('po:manage') && (
              <div>
                <button type="button" onClick={() => setConfirming(true)} className="text-xs text-muted underline hover:text-title">
                  The supplier confirmed another way (phone, in person)
                </button>
              </div>
            )}
            <NoteModal
              open={confirming}
              title={problem ? 'Is the problem sorted out?' : 'Record the supplier\'s confirmation'}
              description={problem ? 'Say what was agreed, for example: new delivery date confirmed by phone. The alert is cleared.' : 'This stops the reminders and clears any alert. Say how they confirmed, for example: rang them, confirmed by phone.'}
              confirmLabel={problem ? 'Sorted out' : 'Record confirmation'}
              loading={confirm.isPending}
              error={confirm.error}
              onClose={() => {
                setConfirming(false)
                confirm.reset()
              }}
              onConfirm={(note) => confirm.mutate(note, { onSuccess: () => setConfirming(false) })}
            />
            {failed && (
              <div className="flex items-start gap-2 rounded-xl bg-danger-soft px-3 py-2.5 text-xs text-danger">
                <AlertTriangle size={16} className="mt-0.5 shrink-0" />
                <span>
                  The order could not be emailed. Check the vendor has an email address on the Vendors page, then retry.
                </span>
              </div>
            )}
            {failed && can('po:manage') && (
              <div>
                <Button variant="secondary" loading={retry.isPending} onClick={() => retry.mutate()}>
                  <RefreshCw size={16} /> Retry sending
                </Button>
                {retry.error && <p className="mt-2 text-sm text-danger">{retry.error.message}</p>}
              </div>
            )}
          </div>
        )}
      </QueryState>
    </Card>
  )
}

function DeliveryCard({ caseId }: { caseId: string }) {
  const { can } = useAuth()
  const delivery = useDelivery(caseId)
  const confirm = useConfirmDelivery(caseId)
  const [confirming, setConfirming] = useState(false)
  const [followingUp, setFollowingUp] = useState(false)
  const [closingShort, setClosingShort] = useState(false)
  const caseStatus = useCase(caseId)
  const shortClose = useShortClose(caseId)
  const d = delivery.data
  const receipt = useReceiptForStaff(caseId, d?.delivery_status === 'delivered')
  const handled = useDisputeHandled(caseId)

  return (
    <Card title="Delivery">
      <QueryState
        variant="detail" rows={4}
        isLoading={delivery.isLoading}
        error={delivery.error}
        isEmpty={!d}
        emptyMessage="Nothing to deliver yet."
      >
        {d && (
          <div className="flex flex-col gap-3">
            <dl className="grid grid-cols-[8rem_1fr] items-center gap-y-3 text-sm">
              <Row label="Order">{d.po_number}</Row>
              <Row label="Expected by">{formatDate(d.expected_delivery_date)}</Row>
              <Row label="Status">
                <Badge value={d.delivery_status} />
              </Row>
              {d.delivery_status === 'delivered' ? (
                <>
                  <Row label="Received">{formatDateTime(d.delivered_at)}</Row>
                  <Row label="Received by">{d.received_by ?? '—'}</Row>
                  {d.delivery_note && <Row label="Note">{d.delivery_note}</Row>}
                </>
              ) : (
                <Row label="Vendor chased">{d.chase_count} time(s) automatically</Row>
              )}
              {d.batches.length > 0 && <Row label="Arrived so far">{d.received_units} of {d.ordered_units}{d.short_closed_at ? ' (rest accepted as not coming)' : ''}</Row>}
            </dl>
            {d.batches.length > 0 && (
              <ul className="divide-y divide-line rounded-xl border border-line text-xs">
                {d.items.map((l) => (
                  <li key={l.description} className="flex items-center justify-between gap-3 px-3 py-2">
                    <span className="min-w-0 truncate text-title">{l.description}</span>
                    <span className="shrink-0 tabular-nums text-muted">
                      {l.received} of {l.ordered}
                      {l.outstanding > 0 && <b className="ml-2 text-amber-700">{l.outstanding} still owed</b>}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {d.escalated_at && d.delivery_status !== 'delivered' && (
              <div className="flex items-start gap-2 rounded-xl bg-danger-soft px-3 py-2.5 text-xs text-danger">
                <AlertTriangle size={16} className="mt-0.5 shrink-0" />
                <span>Overdue, and the vendor has not delivered after repeated follow-ups. Please contact them.</span>
              </div>
            )}
            {d.delivery_status === 'delivered' && receipt.data?.state === 'confirmed' && (
              <p className="rounded-xl bg-[#DCFCE7] px-3 py-2 text-xs text-[#16A34A]">The requester also confirmed the goods reached them.</p>
            )}
            {d.delivery_status === 'delivered' && receipt.data?.state === 'disputed' && (
              <div className="flex flex-col gap-2 rounded-xl bg-danger-soft px-3 py-2.5 text-xs text-danger">
                <span className="flex items-start gap-2">
                  <AlertTriangle size={16} className="mt-0.5 shrink-0" />
                  <span>
                    The requester says the goods have NOT reached them{receipt.data.note ? `: “${receipt.data.note}”` : ''}. Please contact them.
                  </span>
                </span>
                {can('delivery:confirm') && (
                  <div>
                    <Button variant="secondary" onClick={() => setFollowingUp(true)}>
                      I have followed up
                    </Button>
                  </div>
                )}
              </div>
            )}
            {d.delivery_status === 'delivered' && receipt.data?.state === 'followed_up' && (
              <p className="rounded-xl bg-brand-tint px-3 py-2 text-xs text-title">Followed up. Waiting for the requester to confirm again.</p>
            )}
            <GoodsIssuePanel caseId={caseId} delivery={d} caseOpen={caseStatus.data?.status === 'open'} />
            <NoteModal
              open={followingUp}
              title="Record your follow-up"
              description="Say what you did, for example: called the courier, resent the missing item. The requester is then asked again."
              confirmLabel="Save follow-up"
              loading={handled.isPending}
              error={handled.error}
              onClose={() => {
                setFollowingUp(false)
                handled.reset()
              }}
              onConfirm={(note) => handled.mutate(note, { onSuccess: () => setFollowingUp(false) })}
            />
            {d.delivery_status !== 'delivered' && can('delivery:confirm') && (
              <div>
                <Button onClick={() => setConfirming(true)}>
                  <PackageCheck size={16} /> {d.partial ? 'Record more that arrived' : 'Mark as received'}
                </Button>
                {d.partial && (
                  <button type="button" onClick={() => setClosingShort(true)} className="ml-4 text-xs text-muted underline hover:text-title">
                    The supplier will not send the rest
                  </button>
                )}
              </div>
            )}
            <NoteModal
              open={closingShort}
              title="Accept the order as it stands?"
              description={`Only ${d.received_units} of ${d.ordered_units} arrived. This closes the delivery, stops the follow-ups, and the supplier is then billed for what came. Say why, for example: supplier discontinued the item.`}
              confirmLabel="Accept and close the delivery"
              danger
              loading={shortClose.isPending}
              error={shortClose.error}
              onClose={() => {
                setClosingShort(false)
                shortClose.reset()
              }}
              onConfirm={(note) => shortClose.mutate(note, { onSuccess: () => setClosingShort(false) })}
            />
            <ReceiveModal
              open={confirming}
              delivery={d}
              loading={confirm.isPending}
              error={confirm.error}
              onClose={() => {
                setConfirming(false)
                confirm.reset()
              }}
              onConfirm={(note, items) => confirm.mutate({ note, items }, { onSuccess: () => setConfirming(false) })}
            />
          </div>
        )}
      </QueryState>
    </Card>
  )
}
