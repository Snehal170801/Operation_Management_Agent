import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Check, TrendingUp, TriangleAlert, X } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { NoteModal } from '@/components/ui/NoteModal'
import { QueryState } from '@/components/ui/QueryState'
import { useAuth } from '@/features/auth/AuthContext'
import { formatAmount } from '@/lib/format'
import { useApprovalReview, useDecideApproval } from '../hooks'

/** A supplier asks for a higher price on an order already placed. Nothing changes until an approver decides. */
export function PriceChangeCard({ approvalId }: { approvalId: string }) {
  const { user } = useAuth()
  const review = useApprovalReview(approvalId)
  const decide = useDecideApproval()
  const [mode, setMode] = useState<'accept' | 'refuse' | null>(null)
  const r = review.data
  const p = r?.price_change
  const own = !!r && !!user && (r.requested_by ?? '').toLowerCase() === user.username.toLowerCase()

  const close = () => {
    setMode(null)
    decide.reset()
  }

  return (
    <Card
      title={r ? `${r.case_number ?? 'Order'} · the supplier asks for a higher price` : 'The supplier asks for a higher price'}
      action={r?.case_number ? <Link to={`/cases/${r.case_id}`} className="font-medium text-brand-ink hover:underline">Open case</Link> : undefined}
      bodyClassName="flex flex-col gap-5 p-5"
    >
      <QueryState variant="detail" rows={4} isLoading={review.isLoading} error={review.error} isEmpty={!r}>
        {r && p && (
          <>
            <p className="flex items-start gap-2.5 rounded-xl bg-amber-50 px-4 py-3 text-sm font-medium text-amber-900">
              <TrendingUp size={17} className="mt-0.5 shrink-0" />
              <span>
                {p.vendor_name} has changed the price of {p.po_number} after the order was placed. The order stays as it is until you decide.
              </span>
            </p>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div className="rounded-xl bg-brand-tint/60 px-4 py-3">
                <p className="text-xs text-muted">Agreed price</p>
                <p className="mt-0.5 text-xl font-semibold tabular-nums text-title">{formatAmount(p.agreed_total)}</p>
              </div>
              <div className="rounded-xl bg-danger-soft px-4 py-3">
                <p className="text-xs text-muted">Now asking</p>
                <p className="mt-0.5 text-xl font-semibold tabular-nums text-danger">{formatAmount(p.new_total)}</p>
              </div>
              <div className="rounded-xl bg-brand-tint/60 px-4 py-3">
                <p className="text-xs text-muted">Difference</p>
                <p className="mt-0.5 text-xl font-semibold tabular-nums text-title">
                  {p.agreed_total != null && p.new_total != null ? formatAmount(p.new_total - p.agreed_total) : '—'}
                  {p.pct != null && <span className="ml-1 text-sm font-medium text-danger">(+{p.pct}%)</span>}
                </p>
              </div>
            </div>

            {r.items.length > 0 && (
              <div className="flex flex-wrap gap-2 text-xs">
                {r.items.map((i) => (
                  <span key={i.description} className="rounded-full bg-brand-soft px-3 py-1 font-semibold text-brand-ink">
                    {i.description} × {i.quantity}
                  </span>
                ))}
              </div>
            )}

            {p.reply_text && (
              <section>
                <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">What the supplier wrote</h3>
                <p className="mt-1.5 whitespace-pre-wrap break-words rounded-xl border-l-4 border-line bg-brand-tint/50 px-4 py-3 text-sm text-title">{p.reply_text}</p>
              </section>
            )}

            {r.status === 'pending' && (
              <section className="flex flex-col gap-3 border-t border-line pt-4">
                {own && (
                  <p className="flex items-start gap-2 rounded-xl bg-amber-50 px-4 py-2.5 text-sm text-amber-900">
                    <TriangleAlert size={16} className="mt-0.5 shrink-0" /> You asked for this purchase, so someone else has to decide.
                  </p>
                )}
                <div className="flex flex-wrap gap-3">
                  <Button onClick={() => setMode('accept')} disabled={own}>
                    <Check size={16} /> Accept {formatAmount(p.new_total)}
                  </Button>
                  <Button variant="secondary" onClick={() => setMode('refuse')}>
                    <X size={16} /> Refuse, keep {formatAmount(p.agreed_total)}
                  </Button>
                </div>
              </section>
            )}
          </>
        )}
      </QueryState>

      <NoteModal
        open={mode === 'accept'} title="Accept the higher price?"
        description={`The order total becomes ${formatAmount(p?.new_total)} and ${p?.vendor_name ?? 'the supplier'} is told you accept.`}
        confirmLabel="Accept the new price" loading={decide.isPending} error={decide.error} onClose={close}
        onConfirm={(note) => decide.mutate({ approvalId, approve: true, note }, { onSuccess: close })}
      />
      <NoteModal
        open={mode === 'refuse'} title="Refuse the higher price?"
        description={`${p?.vendor_name ?? 'The supplier'} is asked to honour ${formatAmount(p?.agreed_total)} or tell you they cannot. The order stays open and the purchasing team follows up.`}
        confirmLabel="Refuse" danger loading={decide.isPending} error={decide.error} onClose={close}
        onConfirm={(note) => decide.mutate({ approvalId, approve: false, note }, { onSuccess: close })}
      />
    </Card>
  )
}
