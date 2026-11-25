import { useEffect, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { Check, CircleAlert, Clock, Siren, Workflow, X } from 'lucide-react'
import clsx from 'clsx'
import { api, ApiError } from '@/lib/api-client'
import { formatAmount, formatDate, formatDateTime } from '@/lib/format'

interface Info {
  kind: 'vendor_selection' | 'price_change'
  case_number: string | null
  recipient: string
  request_text: string | null
  items: { description: string; quantity: number }[]
  reasons: string[]
  urgent: boolean
  needed_by: string | null
  chosen: { vendor_name: string; price: number | null; lead_time_days: number | null; terms: string | null; tags: string[] } | null
  other_offers: number
  price_change: { po_number: string | null; vendor_name: string | null; agreed_total: number | null; new_total: number | null; pct: number | null } | null
  expires_at: string
  can_decide: boolean
  blocked: string | null
}
interface Result {
  outcome: 'approved' | 'refused'
  message: string
}

const SAD: Record<string, string> = {
  used: 'This link has already been used.',
  expired: 'This link has expired. Please open the app to decide.',
  revoked: 'This link is no longer needed: a newer email replaced it, or the order was decided another way.',
  decided: 'This order has already been decided.',
  person: 'This link was sent to someone who can no longer approve orders.',
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-dvh bg-[#f7f7fa] px-4 py-6 sm:py-12">
      <div className="mx-auto flex w-full max-w-lg flex-col gap-4">
        <div className="flex items-center gap-2.5 px-1">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-[linear-gradient(135deg,#c53536_0%,#ea4d4e_100%)] text-white">
            <Workflow size={20} strokeWidth={2.2} />
          </span>
          <span className="text-[17px] font-semibold text-title">Operation Agents</span>
        </div>
        {children}
      </div>
    </div>
  )
}

function Notice({ tone, title, children }: { tone: 'good' | 'bad' | 'info'; title: string; children?: React.ReactNode }) {
  const Icon = tone === 'good' ? Check : tone === 'bad' ? CircleAlert : Clock
  return (
    <div className="flex flex-col items-center gap-3 rounded-2xl border border-card-border bg-white px-6 py-10 text-center shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
      <span className={clsx('flex h-14 w-14 items-center justify-center rounded-full', tone === 'good' ? 'bg-[#DCFCE7] text-[#16A34A]' : tone === 'bad' ? 'bg-danger-soft text-danger' : 'bg-brand-tint text-brand-ink')}>
        <Icon size={26} />
      </span>
      <h1 className="text-lg font-semibold text-title">{title}</h1>
      {children && <p className="max-w-sm text-sm text-muted">{children}</p>}
    </div>
  )
}

/** The page behind the Approve / Refuse buttons in an approval email. No login: the link is the credential. Opening it changes
 *  nothing; the decision happens only after the confirming tap. */
export function DecisionPage() {
  const { token = '' } = useParams()
  const [params] = useSearchParams()
  const wanted = params.get('a') === 'refuse' ? 'refuse' : params.get('a') === 'approve' ? 'approve' : null
  const [confirming, setConfirming] = useState<'approve' | 'refuse' | null>(wanted)
  const [note, setNote] = useState('')
  // One look at the order, no cache and no refetching: the link is single-use, so a plain request is all this page needs.
  const [info, setInfo] = useState<{ loading: boolean; data: Info | null; error: unknown }>({ loading: true, data: null, error: null })
  useEffect(() => {
    let live = true
    api.get<Info>(`/decisions/${encodeURIComponent(token)}`).then(
      (data) => live && setInfo({ loading: false, data, error: null }),
      (error) => live && setInfo({ loading: false, data: null, error }),
    )
    return () => { live = false }
  }, [token])
  const decide = useMutation({
    mutationFn: (action: 'approve' | 'refuse') => api.post<Result>(`/decisions/${encodeURIComponent(token)}`, { action, note: note.trim() || undefined }),
  })

  if (decide.data) {
    return (
      <Shell>
        <Notice tone={decide.data.outcome === 'approved' ? 'good' : 'info'} title={decide.data.outcome === 'approved' ? 'Approved' : 'Refused'}>
          {decide.data.message} You can close this page.
        </Notice>
      </Shell>
    )
  }
  if (info.loading) return <Shell><Notice tone="info" title="Opening…" /></Shell>
  if (info.error || !info.data) {
    const status = info.error instanceof ApiError ? info.error.status : 0
    const reason = info.error instanceof ApiError ? info.error.message : ''
    return (
      <Shell>
        <Notice tone="bad" title={status === 429 ? 'Please wait a moment' : status === 404 ? 'This link is not valid' : 'This link cannot be used'}>
          {status === 0 ? "Can't reach the server. Check your connection and try again." : reason || SAD.revoked}
        </Notice>
      </Shell>
    )
  }

  const d = info.data
  const pc = d.price_change
  const error = decide.error?.message
  const gone = decide.error instanceof ApiError && decide.error.status === 410

  if (gone) {
    return <Shell><Notice tone="bad" title="This link can no longer be used">{decide.error?.message}</Notice></Shell>
  }

  return (
    <Shell>
      <div className="flex flex-col gap-4 rounded-2xl border border-card-border bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
        <div>
          <p className="text-xs font-medium text-muted">Hello {d.recipient}</p>
          <h1 className="mt-0.5 text-lg font-semibold text-title">
            {d.kind === 'price_change' ? 'A supplier asks for a higher price' : 'An order needs your approval'}
            {d.case_number ? ` · ${d.case_number}` : ''}
          </h1>
          {d.urgent && (
            <span className="mt-2 inline-flex items-center gap-1 rounded-full bg-danger-soft px-2.5 py-0.5 text-[11px] font-semibold text-danger">
              <Siren size={11} /> URGENT{d.needed_by ? ` · needed by ${formatDate(d.needed_by)}` : ''}
            </span>
          )}
        </div>

        {pc ? (
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-xl bg-brand-tint/60 px-4 py-3">
              <p className="text-xs text-muted">Agreed price</p>
              <p className="text-lg font-semibold tabular-nums text-title">{formatAmount(pc.agreed_total)}</p>
            </div>
            <div className="rounded-xl bg-danger-soft px-4 py-3">
              <p className="text-xs text-muted">Now asking{pc.pct != null ? ` (+${pc.pct}%)` : ''}</p>
              <p className="text-lg font-semibold tabular-nums text-danger">{formatAmount(pc.new_total)}</p>
            </div>
            <p className="col-span-2 text-sm text-muted">{pc.vendor_name} · {pc.po_number}</p>
          </div>
        ) : (
          d.chosen && (
            <div className="rounded-xl bg-brand-tint/60 px-4 py-3">
              <p className="text-xs text-muted">Recommended supplier</p>
              <p className="text-base font-semibold text-title">{d.chosen.vendor_name}</p>
              <p className="mt-0.5 text-2xl font-semibold tabular-nums text-title">{formatAmount(d.chosen.price)}</p>
              <p className="mt-0.5 text-sm text-muted">
                {[d.chosen.lead_time_days != null ? `${d.chosen.lead_time_days} days` : null, d.chosen.terms].filter(Boolean).join(' · ')}
              </p>
              {d.chosen.tags.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {d.chosen.tags.map((t) => (
                    <span key={t} className="rounded-full bg-white px-2 py-0.5 text-[11px] font-semibold text-brand-ink">{t}</span>
                  ))}
                </div>
              )}
              {d.other_offers > 0 && <p className="mt-2 text-xs text-muted">{d.other_offers} other offer{d.other_offers === 1 ? '' : 's'} in the app, if you would rather choose a different supplier.</p>}
            </div>
          )
        )}

        {d.items.length > 0 && (
          <ul className="flex flex-wrap gap-2 text-xs">
            {d.items.map((i) => (
              <li key={i.description} className="rounded-full bg-brand-soft px-3 py-1 font-semibold text-brand-ink">{i.description} × {i.quantity}</li>
            ))}
          </ul>
        )}
        {d.request_text && <p className="rounded-xl bg-brand-tint px-4 py-3 text-sm italic text-title">“{d.request_text}”</p>}

        {d.reasons.length > 0 && (
          <div className="rounded-xl bg-amber-50 px-4 py-3 text-sm text-amber-900">
            <p className="font-semibold">Why a person is needed</p>
            <ul className="mt-1 list-disc pl-5">{d.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
          </div>
        )}

        {!d.can_decide ? (
          <p className="rounded-xl bg-amber-50 px-4 py-3 text-sm text-amber-900">{d.blocked}</p>
        ) : !confirming ? (
          <div className="grid grid-cols-2 gap-3">
            <button type="button" onClick={() => setConfirming('approve')} className="flex h-12 items-center justify-center gap-2 rounded-xl bg-[#16A34A] text-sm font-semibold text-white hover:opacity-90">
              <Check size={17} /> Approve
            </button>
            <button type="button" onClick={() => setConfirming('refuse')} className="flex h-12 items-center justify-center gap-2 rounded-xl border border-danger bg-white text-sm font-semibold text-danger hover:bg-danger-soft">
              <X size={17} /> Refuse
            </button>
          </div>
        ) : (
          <div className="flex flex-col gap-3 border-t border-line pt-4">
            <p className="text-sm font-semibold text-title">
              {confirming === 'approve'
                ? pc ? `Accept the new price of ${formatAmount(pc.new_total)}?` : `Order from ${d.chosen?.vendor_name ?? 'this supplier'} for ${formatAmount(d.chosen?.price)}?`
                : pc ? `Refuse the higher price and keep ${formatAmount(pc.agreed_total)}?` : 'Refuse these offers? The request ends and nothing is ordered.'}
            </p>
            {confirming === 'refuse' && (
              <textarea
                value={note} onChange={(e) => setNote(e.target.value)} rows={2} maxLength={500} placeholder="Why? (optional)" aria-label="Why?"
                className="w-full rounded-xl border border-line bg-white px-3 py-2 text-sm text-title focus:border-brand focus:outline-none focus:ring-4 focus:ring-brand/15"
              />
            )}
            {error && <p className="text-sm text-danger">{error}</p>}
            <div className="grid grid-cols-2 gap-3">
              <button type="button" onClick={() => { setConfirming(null); decide.reset() }} className="h-12 rounded-xl border border-line bg-white text-sm font-semibold text-title hover:bg-brand-tint">
                Back
              </button>
              <button
                type="button" disabled={decide.isPending} onClick={() => decide.mutate(confirming)}
                className={clsx('h-12 rounded-xl text-sm font-semibold text-white hover:opacity-90 disabled:opacity-60', confirming === 'approve' ? 'bg-[#16A34A]' : 'bg-danger')}
              >
                {decide.isPending ? 'Please wait…' : confirming === 'approve' ? 'Yes, approve' : 'Yes, refuse'}
              </button>
            </div>
          </div>
        )}
        <p className="text-center text-xs text-muted">This link is only for you, works once, and expires {formatDateTime(d.expires_at)}.</p>
      </div>
    </Shell>
  )
}
