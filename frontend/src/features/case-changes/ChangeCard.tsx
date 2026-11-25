import { useState, type FormEvent } from 'react'
import { Ban, Hourglass, PencilLine } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { Textarea } from '@/components/ui/Field'
import { Modal } from '@/components/ui/Modal'
import { NoteModal } from '@/components/ui/NoteModal'
import { useCancelCase, useChangeCase, useChangeOptions, type ChangeOptions } from './changes'

const CANCEL_HELP: Record<string, string> = {
  before_order: 'No order has gone to a supplier yet. The request ends now and any supplier we asked for a price is told to disregard it.',
  after_order: 'The order is already with the supplier, so we will ask them to cancel it. It stays live until they agree, and the purchasing team steps in if they cannot.',
  from_stock: 'This was filled from stock. Cancelling puts it back on the shelf count and tells Stores, who check it was not already handed over.',
}

function ChangeForm({ options, loading, error, onClose, onConfirm }: {
  options: ChangeOptions
  loading: boolean
  error: Error | null
  onClose: () => void
  onConfirm: (quantities: Record<string, number>, note?: string) => void
}) {
  const [qty, setQty] = useState<Record<string, string>>(() => Object.fromEntries(options.items.map((i) => [i.description, String(i.quantity)])))
  const [note, setNote] = useState('')
  const changed = options.items.filter((i) => Number(qty[i.description]) !== i.quantity)
  const invalid = options.items.some((i) => !Number.isInteger(Number(qty[i.description])) || Number(qty[i.description]) < 1)

  function submit(e: FormEvent) {
    e.preventDefault()
    if (invalid || changed.length === 0) return
    onConfirm(Object.fromEntries(changed.map((i) => [i.description, Number(qty[i.description])])), note.trim() || undefined)
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <p className="text-sm text-muted">
        {options.phase === 'before_order'
          ? 'Suppliers will be asked again for the new quantities, and any quote or approval so far is set aside.'
          : 'The order is already with the supplier. Your change goes to the purchasing team, who agree it with them. Nothing changes until they do.'}
      </p>
      <ul className="divide-y divide-line rounded-xl border border-line">
        {options.items.map((i) => (
          <li key={i.description} className="flex items-center justify-between gap-3 px-4 py-3">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-title">{i.description}</p>
              <p className="text-xs text-muted">Now {i.quantity}</p>
            </div>
            <input
              type="number" min={1} step={1} inputMode="numeric" aria-label={`New quantity of ${i.description}`}
              value={qty[i.description]} onChange={(e) => setQty((q) => ({ ...q, [i.description]: e.target.value }))}
              className="h-11 w-24 rounded-xl border border-line bg-white px-3 text-right text-sm font-semibold text-title focus:border-brand focus:outline-none focus:ring-4 focus:ring-brand/15"
            />
          </li>
        ))}
      </ul>
      <p className="text-xs text-muted">To remove an item altogether, cancel the request and make a new one.</p>
      <Textarea label="Why? (optional)" rows={2} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
      {error && <p className="text-sm text-danger">{error.message}</p>}
      <div className="flex justify-end gap-3">
        <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
        <Button type="submit" loading={loading} disabled={invalid || changed.length === 0}>Send the change</Button>
      </div>
    </form>
  )
}

/** Change the quantities of a request, or cancel it: for the person who asked, and for staff who edit cases. */
export function ChangeCard({ caseId }: { caseId: string }) {
  const options = useChangeOptions(caseId)
  const cancel = useCancelCase(caseId)
  const change = useChangeCase(caseId)
  const [mode, setMode] = useState<'cancel' | 'change' | null>(null)
  const o = options.data
  if (!o || o.phase === 'closed') return null

  const close = () => {
    setMode(null)
    cancel.reset()
    change.reset()
  }

  return (
    <Card title="Change or cancel this request">
      <div className="flex flex-col gap-4 text-sm">
        <p className="flex items-start gap-2 text-muted">
          {o.phase === 'cancelling' && <Hourglass size={16} className="mt-0.5 shrink-0 text-amber-600" />}
          <span>{o.note}</span>
        </p>
        {o.pending_change && (
          <p className="rounded-xl bg-brand-tint px-4 py-3 text-title">
            Your change ({o.pending_change.changes.map((c) => `${c.item}: ${c.from} → ${c.to}`).join('; ')}) has been passed to the purchasing team and is waiting for the supplier to agree.
          </p>
        )}
        {(o.can_change || o.can_cancel) && (
          <div className="flex flex-wrap gap-3">
            {o.can_change && (
              <Button variant="secondary" onClick={() => setMode('change')}>
                <PencilLine size={16} /> Change quantity
              </Button>
            )}
            {o.can_cancel && (
              <Button variant="secondary" onClick={() => setMode('cancel')}>
                <Ban size={16} /> Cancel request
              </Button>
            )}
          </div>
        )}
      </div>

      <Modal open={mode === 'change'} title="Change quantity" onClose={close}>
        <ChangeForm
          options={o} loading={change.isPending} error={change.error} onClose={close}
          onConfirm={(quantities, note) => change.mutate({ quantities, note }, { onSuccess: close })}
        />
      </Modal>
      <NoteModal
        open={mode === 'cancel'}
        title="Cancel this request?"
        description={CANCEL_HELP[o.phase] ?? ''}
        confirmLabel="Cancel the request"
        danger
        loading={cancel.isPending}
        error={cancel.error}
        onClose={close}
        onConfirm={(reason) => cancel.mutate(reason, { onSuccess: close })}
      />
    </Card>
  )
}
