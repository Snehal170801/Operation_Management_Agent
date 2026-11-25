import { useState, type FormEvent } from 'react'
import { AlertTriangle, Check, Undo2 } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Input, Textarea } from '@/components/ui/Field'
import { Modal } from '@/components/ui/Modal'
import { NoteModal } from '@/components/ui/NoteModal'
import type { PurchaseOrder } from '@/features/purchase-orders/types'
import { useChangeOptions, useResolveCancel, useResolveChange } from './changes'

function AmendForm({ loading, error, onClose, onConfirm }: {
  loading: boolean
  error: Error | null
  onClose: () => void
  onConfirm: (total: number | undefined, note: string | undefined) => void
}) {
  const [total, setTotal] = useState('')
  const [note, setNote] = useState('')
  const bad = total !== '' && !(Number(total) > 0)
  function submit(e: FormEvent) {
    e.preventDefault()
    if (!bad) onConfirm(total === '' ? undefined : Number(total), note.trim() || undefined)
  }
  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <p className="text-sm text-muted">The order will carry the new quantities. If the price changed with them, enter the new order total; otherwise leave it as it is.</p>
      <Input label="New order total (optional)" type="number" min={0} step="any" value={total} onChange={(e) => setTotal(e.target.value)} />
      <Textarea label="What was agreed? (optional)" rows={2} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
      {error && <p className="text-sm text-danger">{error.message}</p>}
      <div className="flex justify-end gap-3">
        <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
        <Button type="submit" loading={loading} disabled={bad}>Order amended</Button>
      </div>
    </form>
  )
}

/** For the purchasing team: a cancellation the supplier refused or ignored, and a change the requester asked for. */
export function PoDeskPanel({ caseId, po }: { caseId: string; po: PurchaseOrder }) {
  const options = useChangeOptions(caseId)
  const cancel = useResolveCancel(caseId)
  const change = useResolveChange(caseId)
  const [mode, setMode] = useState<'settled' | 'carry_on' | 'amended' | 'declined' | null>(null)
  const pending = options.data?.pending_change
  const cancelling = po.status === 'sent' && !!po.cancel_requested_at
  if (!cancelling && !pending) return null

  const close = () => {
    setMode(null)
    cancel.reset()
    change.reset()
  }

  return (
    <div className="flex flex-col gap-3">
      {cancelling && (
        <div className="flex flex-col gap-2 rounded-xl bg-danger-soft px-3 py-2.5 text-xs text-danger">
          <span className="flex items-start gap-2">
            <AlertTriangle size={16} className="mt-0.5 shrink-0" />
            <span>
              {po.cancel_requested_by ?? 'The requester'} cancelled this request{po.cancel_reason ? ` (${po.cancel_reason})` : ''}, so the supplier was asked to cancel the order.
              {po.cancel_refused_at ? ' They say it cannot be cancelled.' : po.cancel_escalated_at ? ' They have not answered after reminders.' : ' Waiting for their answer.'}
            </span>
          </span>
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => setMode('settled')}>
              <Check size={16} /> The supplier cancelled it
            </Button>
            <Button variant="secondary" onClick={() => setMode('carry_on')}>
              <Undo2 size={16} /> Carry on with the order
            </Button>
          </div>
        </div>
      )}
      {pending && (
        <div className="flex flex-col gap-2 rounded-xl bg-brand-tint px-3 py-2.5 text-xs text-title">
          <span>
            {pending.by ?? 'The requester'} asks to change this order: <b>{pending.changes.map((c) => `${c.item}: ${c.from} → ${c.to}`).join('; ')}</b>
            {pending.note ? ` (${pending.note})` : ''}. Agree it with the supplier, then record the result.
          </span>
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => setMode('amended')}>
              <Check size={16} /> Supplier agreed
            </Button>
            <Button variant="secondary" onClick={() => setMode('declined')}>
              Supplier cannot, keep the order as it is
            </Button>
          </div>
        </div>
      )}

      <NoteModal
        open={mode === 'settled'} title="The order is cancelled?"
        description="This closes the request as cancelled. Say how it was settled, for example: supplier confirmed by phone."
        confirmLabel="Close as cancelled" danger loading={cancel.isPending} error={cancel.error} onClose={close}
        onConfirm={(note) => cancel.mutate({ action: 'settled', note }, { onSuccess: close })}
      />
      <NoteModal
        open={mode === 'carry_on'} title="Carry on with the order?"
        description="The cancellation is dropped and the order continues as normal, with delivery follow-ups."
        confirmLabel="Carry on" loading={cancel.isPending} error={cancel.error} onClose={close}
        onConfirm={(note) => cancel.mutate({ action: 'carry_on', note }, { onSuccess: close })}
      />
      <Modal open={mode === 'amended'} title="Record the agreed change" onClose={close}>
        <AmendForm loading={change.isPending} error={change.error} onClose={close}
          onConfirm={(total_amount, note) => change.mutate({ action: 'amended', total_amount, note }, { onSuccess: close })} />
      </Modal>
      <NoteModal
        open={mode === 'declined'} title="Keep the order as it is?"
        description="The change is closed without altering the order. Say why, for example: supplier cannot supply more."
        confirmLabel="Keep the order" loading={change.isPending} error={change.error} onClose={close}
        onConfirm={(note) => change.mutate({ action: 'declined', note }, { onSuccess: close })}
      />
    </div>
  )
}
