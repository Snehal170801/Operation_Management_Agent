import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Check, Clock, Handshake, Lightbulb, RefreshCw, Siren, ShieldCheck, TriangleAlert, X } from 'lucide-react'
import clsx from 'clsx'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { NoteModal } from '@/components/ui/NoteModal'
import { QueryState } from '@/components/ui/QueryState'
import { useAuth } from '@/features/auth/AuthContext'
import { formatAmount, formatDate } from '@/lib/format'
import { useIsPhone } from '@/lib/useIsPhone'
import { useApprovalReview, useDecideApproval } from '../hooks'
import type { ReviewOption } from '../types'
import { RejectModal } from './RejectModal'

const TAG: Record<string, string> = {
  "AI's pick": 'bg-brand-soft text-brand-ink',
  Cheapest: 'bg-emerald-100 text-emerald-800',
  Fastest: 'bg-sky-100 text-sky-800',
}

function Option({ option, selected, disabled, onPick }: { option: ReviewOption; selected: boolean; disabled: boolean; onPick: () => void }) {
  return (
    <label
      className={clsx(
        'flex cursor-pointer flex-col gap-3 rounded-2xl border p-4 transition-colors',
        selected ? 'border-brand bg-brand-tint/60 shadow-[0_0_0_1px_var(--color-brand)]' : 'border-line bg-white hover:bg-brand-tint/30',
        disabled && 'cursor-not-allowed opacity-70',
      )}
    >
      <div className="flex items-start gap-3">
        <input
          type="radio"
          name={`supplier-${option.vendor_id.slice(0, 8)}`}
          checked={selected}
          disabled={disabled}
          onChange={onPick}
          className="mt-1 h-4 w-4 accent-[#ea4d4e]"
          aria-label={`Choose ${option.vendor_name}`}
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            {option.rank && <span className="rounded-md bg-title px-2 py-0.5 text-xs font-semibold text-white">#{option.rank}</span>}
            <span className="text-base font-semibold text-title">{option.vendor_name}</span>
            {option.tags.map((t) => (
              <span key={t} className={clsx('rounded-full px-2.5 py-0.5 text-[11px] font-semibold', TAG[t] ?? 'bg-slate-100 text-slate-700')}>
                {t}
              </span>
            ))}
          </div>
          {option.email && <p className="mt-0.5 break-all text-xs text-muted">{option.email}</p>}
        </div>
        <div className="text-right">
          <p className="text-xl font-semibold tabular-nums text-title">{option.price !== null ? formatAmount(option.price) : '—'}</p>
          <p className="text-xs text-muted">total price</p>
        </div>
      </div>

      <dl className="grid grid-cols-3 gap-2 text-sm">
        <div className="rounded-xl bg-white/80 px-3 py-2">
          <dt className="text-xs text-muted">Delivery</dt>
          <dd className="font-medium text-title">{option.lead_time_days !== null ? `${option.lead_time_days} days` : '—'}</dd>
        </div>
        <div className="rounded-xl bg-white/80 px-3 py-2">
          <dt className="text-xs text-muted">Terms</dt>
          <dd className="break-words font-medium text-title">{option.terms ?? '—'}</dd>
        </div>
        <div className="rounded-xl bg-white/80 px-3 py-2">
          <dt className="text-xs text-muted">Reliability</dt>
          <dd className="font-medium text-title">{option.reliability !== null ? `${option.reliability} / 5` : '—'}</dd>
        </div>
      </dl>

      {option.reason && (
        <p className="flex items-start gap-2 text-sm text-title">
          <ShieldCheck size={16} className="mt-0.5 shrink-0 text-brand" />
          <span>
            <b className="font-semibold">Why this place:</b> {option.reason}
          </span>
        </p>
      )}
      {option.reply_text && (
        <blockquote className="whitespace-pre-wrap break-words rounded-xl border-l-4 border-line bg-white px-3 py-2 text-sm text-muted">
          <span className="mb-0.5 block text-[11px] font-semibold uppercase tracking-wide text-muted/80">What they wrote</span>
          {option.reply_text}
        </blockquote>
      )}
    </label>
  )
}

/** One decision, in full: what was asked, every supplier's reply with the AI's ranking and reasons, and the
 *  person's own choice of supplier. Re-reads itself the moment a quote arrives or the ranking changes (live). */
export function ApprovalReviewCard({ approvalId }: { approvalId: string }) {
  const { user } = useAuth()
  const review = useApprovalReview(approvalId)
  const decide = useDecideApproval()
  const [picked, setPicked] = useState<string>()
  const [mode, setMode] = useState<'approve' | 'reject' | null>(null)
  const phone = useIsPhone()
  const [opened, setOpened] = useState(false)           // on a phone each decision starts as a short summary; the full picture is one tap away
  const r = review.data
  const selectedName = r?.options.find((o) => o.vendor_id === r.selected_vendor_id)?.vendor_name

  const chosenId = picked && r?.options.some((o) => o.vendor_id === picked) ? picked : (r?.selected_vendor_id ?? r?.options[0]?.vendor_id)
  const chosen = r?.options.find((o) => o.vendor_id === chosenId)
  const aiPick = r?.options.find((o) => o.vendor_id === r.recommended_vendor_id)
  const own = !!r && !!user && (r.requested_by ?? '').toLowerCase() === user.username.toLowerCase()
  const differs = !!chosen && !!aiPick && chosen.vendor_id !== aiPick.vendor_id
  const open = r?.status === 'pending'
  const compact = phone && open && !opened

  function close() {
    setMode(null)
    decide.reset()
  }

  return (
    <Card
      title={r ? `${r.case_number ?? 'Request'} · needs your decision` : 'Needs your decision'}
      action={r?.case_number ? <Link to={`/cases/${r.case_id}`} className="font-medium text-brand-ink hover:underline">Open case</Link> : undefined}
      className="max-sm:overflow-visible"                  // a clipping card would stop the phone's bottom action bar from sticking
      bodyClassName="flex flex-col gap-5 p-5"
    >
      <QueryState variant="detail" rows={5} isLoading={review.isLoading} error={review.error} isEmpty={!r}>
        {r && compact && (
          <section className="flex flex-col gap-3" aria-label="Summary of this decision">
            {r.urgent && (
              <p className="flex items-center gap-2 rounded-xl bg-danger-soft px-3 py-2 text-sm font-semibold text-danger">
                <Siren size={16} /> URGENT{r.needed_by ? `: needed by ${formatDate(r.needed_by)}` : ''}
              </p>
            )}
            {r.request_text && <p className="line-clamp-2 break-words text-sm text-title">{r.request_text}</p>}
            <div className="flex flex-wrap items-center gap-2">
              {r.items.slice(0, 3).map((i) => (
                <span key={i.description} className="rounded-full bg-brand-soft px-3 py-1 text-xs font-semibold text-brand-ink">{i.description} × {i.quantity}</span>
              ))}
              {r.items.length > 3 && <span className="text-xs text-muted">+{r.items.length - 3} more</span>}
            </div>
            {chosen && (
              <div className="rounded-xl bg-brand-tint/70 px-3 py-2.5">
                <p className="text-xs text-muted">{aiPick && chosen.vendor_id === aiPick.vendor_id ? "The AI's pick" : 'Chosen supplier'}</p>
                <p className="flex flex-wrap items-baseline justify-between gap-x-3 text-title">
                  <span className="font-semibold">{chosen.vendor_name}</span>
                  <span className="text-lg font-semibold tabular-nums">{chosen.price !== null ? formatAmount(chosen.price) : '—'}</span>
                </p>
                <p className="text-xs text-muted">{chosen.lead_time_days !== null ? `${chosen.lead_time_days} days` : 'delivery time not stated'} · {r.options.length} supplier{r.options.length === 1 ? '' : 's'} replied</p>
              </div>
            )}
            <p className="line-clamp-2 flex items-start gap-2 text-sm text-amber-900"><TriangleAlert size={16} className="mt-0.5 shrink-0" /> {r.reasons[0] ?? 'A person is needed.'}</p>
            <Button className="h-12 w-full" onClick={() => setOpened(true)}>Review and decide</Button>
          </section>
        )}

        {r && !compact && (
          <>
            {phone && open && (
              <button type="button" onClick={() => setOpened(false)} className="-mb-2 self-start text-sm font-medium text-brand-ink hover:underline">
                ← Back to the summary
              </button>
            )}
            {r.urgent && (
              <p className="flex items-center gap-2 rounded-xl bg-danger-soft px-4 py-3 text-sm font-semibold text-danger">
                <Siren size={16} /> URGENT{r.needed_by ? `: the goods are needed by ${formatDate(r.needed_by)}` : ''}
              </p>
            )}

            {r.round > 1 && (
              <p className="flex items-start gap-2 rounded-xl bg-sky-50 px-4 py-3 text-sm text-sky-900">
                <RefreshCw size={16} className="mt-0.5 shrink-0" />
                <span>
                  <b>Round {r.round}.</b> The suppliers were asked again after the earlier offers were turned down{r.earlier_note ? `: “${r.earlier_note}”` : ''}. Only the new offers are shown.
                </span>
              </p>
            )}

            <section className="flex flex-col gap-2 rounded-xl bg-amber-50 px-4 py-3 text-sm text-amber-900">
              <p className="flex items-center gap-2 font-semibold">
                <TriangleAlert size={16} /> Why a person is needed
              </p>
              <ul className="list-disc pl-5">
                {r.reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            </section>

            {open && r.negotiation && (
              <p className={'flex items-start gap-2.5 rounded-xl px-4 py-3 text-sm font-medium ' + (r.negotiation.outcome === 'improved' ? 'bg-emerald-50 text-emerald-900' : 'bg-page text-title')}>
                <Handshake size={17} className="mt-0.5 shrink-0" />
                <span>{r.negotiation.text}</span>
              </p>
            )}

            {open && r.suggestion && (
              <p className="flex items-start gap-2.5 rounded-xl bg-emerald-50 px-4 py-3 text-sm font-medium text-emerald-900">
                <Lightbulb size={17} className="mt-0.5 shrink-0" />
                <span>{r.suggestion}</span>
              </p>
            )}

            <section>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">What was asked</h3>
              {r.request_text && <p className="mt-1.5 whitespace-pre-wrap break-words rounded-xl bg-brand-tint px-4 py-3 text-sm text-title">{r.request_text}</p>}
              <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
                {r.items.map((i) => (
                  <span key={i.description} className="rounded-full bg-brand-soft px-3 py-1 text-xs font-semibold text-brand-ink">
                    {i.description} × {i.quantity}
                  </span>
                ))}
                {r.requested_by && <span className="text-xs text-muted">Requested by {r.requested_by}</span>}
              </div>
            </section>

            <section className="flex flex-col gap-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">
                  {r.options.length} supplier{r.options.length === 1 ? '' : 's'} replied · ranked best first by the AI
                </h3>
                {open && <p className="text-xs text-muted">Choose the supplier to order from. The AI's pick is selected for you.</p>}
              </div>
              {r.options.length === 0 ? (
                <p className="flex items-center gap-2 rounded-xl bg-brand-tint px-4 py-3 text-sm text-muted">
                  <Clock size={16} /> No replies yet. They will appear here as they arrive.
                </p>
              ) : (
                <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
                  {r.options.map((o) => (
                    <Option key={o.vendor_id} option={o} selected={o.vendor_id === chosenId} disabled={!open} onPick={() => setPicked(o.vendor_id)} />
                  ))}
                </div>
              )}
            </section>

            {open && chosen && (
              <section className="flex flex-col gap-3 border-t border-line pt-4 max-sm:sticky max-sm:bottom-0 max-sm:z-10 max-sm:-mx-5 max-sm:-mb-5 max-sm:rounded-b-2xl max-sm:bg-white max-sm:px-5 max-sm:pb-[calc(1rem+env(safe-area-inset-bottom))] max-sm:shadow-[0_-8px_16px_rgba(0,0,0,0.06)]">
                {differs && aiPick && (
                  <p className="flex items-start gap-2 rounded-xl bg-amber-50 px-4 py-2.5 text-sm text-amber-900">
                    <TriangleAlert size={16} className="mt-0.5 shrink-0" />
                    <span>
                      You chose <b>{chosen.vendor_name}</b> instead of the AI's pick, <b>{aiPick.vendor_name}</b>. Your choice is recorded with your name.
                    </span>
                  </p>
                )}
                {own && (
                  <p className="flex items-start gap-2 rounded-xl bg-amber-50 px-4 py-2.5 text-sm text-amber-900">
                    <TriangleAlert size={16} className="mt-0.5 shrink-0" /> You asked for this purchase, so someone else has to approve it.
                  </p>
                )}
                <div className="flex flex-wrap gap-3 max-sm:flex-col">
                  <Button className="max-sm:h-12 max-sm:w-full" onClick={() => setMode('approve')} disabled={own || chosen.price === null}>
                    <Check size={16} /> Approve and order from {chosen.vendor_name}
                  </Button>
                  <Button variant="secondary" className="max-sm:h-12 max-sm:w-full" onClick={() => setMode('reject')}>
                    <X size={16} /> Reject
                  </Button>
                </div>
              </section>
            )}
          </>
        )}
      </QueryState>

      <NoteModal
        open={mode === 'approve'}
        title={`Order from ${chosen?.vendor_name}?`}
        description={`A purchase order for ${chosen && chosen.price !== null ? formatAmount(chosen.price) : 'the quoted price'} will be created and emailed to ${chosen?.vendor_name} straight away.`}
        confirmLabel="Approve and send the order"
        loading={decide.isPending}
        error={decide.error}
        onClose={close}
        onConfirm={(note) => decide.mutate({ approvalId, approve: true, note, vendorId: chosenId }, { onSuccess: close })}
      />
      <RejectModal
        open={mode === 'reject'}
        canAskAgain={!!r?.can_ask_again}
        selectedSupplier={selectedName}
        loading={decide.isPending}
        error={decide.error}
        onClose={close}
        onConfirm={({ note, reSource, skipSelected }) =>
          decide.mutate({ approvalId, approve: false, note, reSource, skipSelected }, { onSuccess: close })
        }
      />
    </Card>
  )
}
