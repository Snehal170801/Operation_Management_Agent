import { useState, type FormEvent } from 'react'
import { AlertTriangle, Check, PackageCheck, PackageX, Undo2 } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Input, Textarea } from '@/components/ui/Field'
import { Modal } from '@/components/ui/Modal'
import { NoteModal } from '@/components/ui/NoteModal'
import { useConfirm } from '@/components/ui/confirm-context'
import { useAuth } from '@/features/auth/AuthContext'
import type { Delivery } from '@/features/delivery/types'
import { formatAmount, formatDateTime } from '@/lib/format'
import { KIND_LABEL, useExpectReplacement, useGoodsIssues, useReceiveReplacement, useReportIssue, useResolveIssue, useReturnGoods, type GoodsIssue, type IssueKind } from './issues'

function ReportForm({ delivery, loading, error, onClose, onConfirm }: {
  delivery: Delivery
  loading: boolean
  error: Error | null
  onClose: () => void
  onConfirm: (v: { kind: IssueKind; items: Record<string, number>; description?: string }) => void
}) {
  const arrived = delivery.items.filter((l) => l.received > 0)
  const [kind, setKind] = useState<IssueKind>('damaged')
  const [qty, setQty] = useState<Record<string, string>>(() => Object.fromEntries(arrived.map((l) => [l.description, '0'])))
  const [description, setDescription] = useState('')
  const picked = arrived.filter((l) => Number(qty[l.description]) > 0)
  const bad = arrived.some((l) => !Number.isInteger(Number(qty[l.description])) || Number(qty[l.description]) < 0 || Number(qty[l.description]) > l.received)
  const needsText = kind === 'other' && !description.trim()

  function submit(e: FormEvent) {
    e.preventDefault()
    if (bad || picked.length === 0 || needsText) return
    onConfirm({ kind, items: Object.fromEntries(picked.map((l) => [l.description, Number(qty[l.description])])), description: description.trim() || undefined })
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <p className="text-sm text-muted">The supplier is emailed straight away and asked to replace the items or issue a credit note. Payment for this order is held until you record how it ended.</p>
      <fieldset className="grid gap-2 sm:grid-cols-2">
        <legend className="mb-1 text-xs font-medium text-muted">What is wrong?</legend>
        {(Object.keys(KIND_LABEL) as IssueKind[]).map((k) => (
          <label key={k} className={`flex cursor-pointer items-center gap-2 rounded-xl border px-3 py-2.5 text-sm ${kind === k ? 'border-brand bg-brand-tint' : 'border-line'}`}>
            <input type="radio" name="kind" checked={kind === k} onChange={() => setKind(k)} className="accent-[#c53536]" /> {KIND_LABEL[k]}
          </label>
        ))}
      </fieldset>
      <ul className="divide-y divide-line rounded-xl border border-line">
        {arrived.map((l) => (
          <li key={l.description} className="flex items-center justify-between gap-3 px-4 py-3">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-title">{l.description}</p>
              <p className="text-xs text-muted">{l.received} arrived. How many are affected?</p>
            </div>
            <input
              type="number" min={0} max={l.received} step={1} inputMode="numeric" aria-label={`How many ${l.description} are affected`}
              value={qty[l.description]} onChange={(e) => setQty((q) => ({ ...q, [l.description]: e.target.value }))}
              className="h-11 w-24 rounded-xl border border-line bg-white px-3 text-right text-sm font-semibold text-title focus:border-brand focus:outline-none focus:ring-4 focus:ring-brand/15"
            />
          </li>
        ))}
      </ul>
      <Textarea label={kind === 'other' ? 'Describe the problem' : 'What did you see? (optional)'} rows={2} maxLength={500} value={description} onChange={(e) => setDescription(e.target.value)} />
      {error && <p className="text-sm text-danger">{error.message}</p>}
      <div className="flex justify-end gap-3">
        <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
        <Button type="submit" loading={loading} disabled={bad || picked.length === 0 || needsText}>Report and tell the supplier</Button>
      </div>
    </form>
  )
}

function ResolveForm({ issue, loading, error, onClose, onConfirm }: {
  issue: GoodsIssue
  loading: boolean
  error: Error | null
  onClose: () => void
  onConfirm: (v: { resolution: 'replaced' | 'credit' | 'accepted'; credit_amount?: number; credit_note_number?: string; note?: string }) => void
}) {
  const [resolution, setResolution] = useState<'replaced' | 'credit' | 'accepted'>('replaced')
  const [amount, setAmount] = useState('')
  const [creditNote, setCreditNote] = useState('')
  const [note, setNote] = useState('')
  const missing = resolution === 'credit' && !(Number(amount) > 0)
  function submit(e: FormEvent) {
    e.preventDefault()
    if (!missing) onConfirm({ resolution, credit_amount: resolution === 'credit' ? Number(amount) : undefined, credit_note_number: resolution === 'credit' ? creditNote.trim() || undefined : undefined, note: note.trim() || undefined })
  }
  const options = [
    ['replaced', 'The supplier replaced the faulty items', 'Nothing changes in what is owed.'],
    ['credit', 'The supplier is giving money back (credit note)', 'The credit comes off what the supplier may bill. Accounts are told to apply it by hand; nothing is paid or changed automatically.'],
    ['accepted', 'We keep the goods as they are', 'Nothing changes in what is owed.'],
  ] as const
  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <p className="text-sm text-muted">{issue.po_number} · {issue.items.map((i) => `${i.description} × ${i.quantity}`).join(', ')}. Closing this releases payment if nothing else is holding it.</p>
      <div className="flex flex-col gap-2">
        {options.map(([value, label, help]) => (
          <label key={value} className={`flex cursor-pointer items-start gap-3 rounded-xl border px-4 py-3 ${resolution === value ? 'border-brand bg-brand-tint' : 'border-line'}`}>
            <input type="radio" name="resolution" checked={resolution === value} onChange={() => setResolution(value)} className="mt-1 accent-[#c53536]" />
            <span><span className="block text-sm font-semibold text-title">{label}</span><span className="text-xs text-muted">{help}</span></span>
          </label>
        ))}
      </div>
      {resolution === 'credit' && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Input label="Credit amount" type="number" min={0} step="any" value={amount} onChange={(e) => setAmount(e.target.value)} />
          <Input label="Credit note number (optional)" maxLength={100} value={creditNote} onChange={(e) => setCreditNote(e.target.value)} />
        </div>
      )}
      <Textarea label="Note (optional)" rows={2} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
      {error && <p className="text-sm text-danger">{error.message}</p>}
      <div className="flex justify-end gap-3">
        <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
        <Button type="submit" loading={loading} disabled={missing}>Close this problem</Button>
      </div>
    </form>
  )
}

/** Problems with goods that arrived (damaged, wrong item...): report one, follow it up, record how it ended. */
export function GoodsIssuePanel({ caseId, delivery, caseOpen }: { caseId: string; delivery: Delivery; caseOpen: boolean }) {
  const { can } = useAuth()
  const issues = useGoodsIssues(caseId)
  const report = useReportIssue(caseId)
  const resolve = useResolveIssue(caseId)
  const giveBack = useReturnGoods(caseId)
  const expectReplacement = useExpectReplacement(caseId)
  const receiveReplacement = useReceiveReplacement(caseId)
  const confirm = useConfirm()
  const [returning, setReturning] = useState<GoodsIssue>()
  const [reporting, setReporting] = useState(false)
  const [resolving, setResolving] = useState<GoodsIssue>()
  const list = issues.data ?? []
  const canAct = can('delivery:confirm')
  const anythingArrived = delivery.items.some((l) => l.received > 0)

  if (!list.length && !(canAct && caseOpen && anythingArrived)) return null

  return (
    <div className="flex flex-col gap-3">
      {list.map((i) => (
        <div key={i.issue_id} className={`flex flex-col gap-1.5 rounded-xl px-3 py-2.5 text-xs ${i.status === 'open' ? 'bg-danger-soft text-danger' : 'bg-brand-tint text-title'}`}>
          <span className="flex items-start gap-2">
            {i.status === 'open' ? <AlertTriangle size={16} className="mt-0.5 shrink-0" /> : <Check size={16} className="mt-0.5 shrink-0 text-[#16A34A]" />}
            <span>
              <b>{KIND_LABEL[i.kind]}:</b> {i.items.map((x) => `${x.description} × ${x.quantity}`).join(', ')}
              {i.description ? ` · “${i.description}”` : ''} · reported by {i.reported_by}, {formatDateTime(i.reported_at)}
            </span>
          </span>
          {i.status === 'open' ? (
            <>
              <span>
                {i.supplier_told_at ? 'The supplier was asked to put it right.' : 'The supplier could NOT be emailed. Please contact them.'}
                {i.supplier_replied_at ? ' They have replied: read it and record how it ended.' : i.escalated_at ? ' No answer after reminders.' : i.chase_count ? ` Reminded ${i.chase_count} time(s).` : ' Waiting for their answer.'}
              </span>
              {i.return_status === 'returned' && (
                <span>Goods sent back{i.return_ref ? ` (ref ${i.return_ref})` : ''}{i.returned_by ? ` by ${i.returned_by}` : ''}, {formatDateTime(i.returned_at)}.</span>
              )}
              {i.replacement_status === 'expected' && <span>The supplier promised a replacement. Payment stays held until it arrives.</span>}
              {(giveBack.error || expectReplacement.error || receiveReplacement.error) && (
                <span role="alert" className="text-danger">{(giveBack.error ?? expectReplacement.error ?? receiveReplacement.error)?.message}</span>
              )}
              {canAct && (
                <div className="flex flex-wrap gap-2">
                  {!i.return_status && (
                    <Button variant="secondary" onClick={() => setReturning(i)}>
                      <Undo2 size={16} /> Mark goods returned
                    </Button>
                  )}
                  {!i.replacement_status && (
                    <Button variant="secondary" loading={expectReplacement.isPending} onClick={() => expectReplacement.mutate(i.issue_id)}>
                      <PackageCheck size={16} /> Replacement promised
                    </Button>
                  )}
                  {i.replacement_status === 'expected' && (
                    <Button
                      variant="secondary"
                      loading={receiveReplacement.isPending}
                      onClick={async () => {
                        const ok = await confirm({ title: 'Replacement arrived?', message: `The replacement for ${i.po_number} has arrived. This closes the problem as replaced and releases payment if nothing else is holding it.`, confirmLabel: 'Yes, it arrived' })
                        if (ok) receiveReplacement.mutate({ issueId: i.issue_id })
                      }}
                    >
                      <Check size={16} /> Replacement arrived
                    </Button>
                  )}
                  <Button variant="secondary" onClick={() => setResolving(i)}>
                    <Check size={16} /> Record how it ended
                  </Button>
                </div>
              )}
            </>
          ) : (
            <span className="text-muted">
              Closed: {i.resolution === 'replaced' ? 'replaced by the supplier' : i.resolution === 'credit' ? `credit of ${formatAmount(i.credit_amount)} agreed${i.credit_note_number ? ` (credit note ${i.credit_note_number})` : ''}` : 'accepted as it is'}
              {i.resolution_note ? ` · “${i.resolution_note}”` : ''} · {i.resolved_by}
            </span>
          )}
        </div>
      ))}
      {canAct && caseOpen && anythingArrived && (
        <div>
          <Button variant="secondary" onClick={() => setReporting(true)}>
            <PackageX size={16} /> Report a problem with the goods
          </Button>
        </div>
      )}

      <Modal open={reporting} title="Report a problem with the goods" onClose={() => { setReporting(false); report.reset() }}>
        <ReportForm delivery={delivery} loading={report.isPending} error={report.error}
          onClose={() => { setReporting(false); report.reset() }}
          onConfirm={(v) => report.mutate(v, { onSuccess: () => setReporting(false) })} />
      </Modal>
      <NoteModal
        open={!!returning}
        title="Goods sent back to the supplier"
        description="Add your return reference if you have one (optional, up to 100 characters). The supplier is told what is coming. Nothing owed and no stock count changes here."
        confirmLabel="Mark as returned"
        loading={giveBack.isPending}
        error={giveBack.error}
        onClose={() => { setReturning(undefined); giveBack.reset() }}
        onConfirm={(ref) => returning && giveBack.mutate({ issueId: returning.issue_id, ref: ref?.trim() || undefined }, { onSuccess: () => setReturning(undefined) })}
      />
      <Modal open={!!resolving} title="How did it end?" onClose={() => { setResolving(undefined); resolve.reset() }}>
        {resolving && (
          <ResolveForm issue={resolving} loading={resolve.isPending} error={resolve.error}
            onClose={() => { setResolving(undefined); resolve.reset() }}
            onConfirm={(v) => resolve.mutate({ issueId: resolving.issue_id, ...v }, { onSuccess: () => setResolving(undefined) })} />
        )}
      </Modal>
    </div>
  )
}
