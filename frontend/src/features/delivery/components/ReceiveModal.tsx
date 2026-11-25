import { useState, type FormEvent } from 'react'
import { Button } from '@/components/ui/Button'
import { Textarea } from '@/components/ui/Field'
import { Modal } from '@/components/ui/Modal'
import type { Delivery } from '../types'

interface ReceiveModalProps {
  open: boolean
  delivery: Delivery
  loading?: boolean
  error?: Error | null
  onClose: () => void
  /** `items` is by item name; left out when everything still owed arrived. */
  onConfirm: (note: string | undefined, items: Record<string, number> | undefined) => void
}

/** Record goods that arrived: one box per item (starting at everything still owed), so a part delivery is just a smaller number. */
export function ReceiveModal({ open, onClose, ...form }: ReceiveModalProps) {
  return (
    <Modal open={open} title="What arrived?" onClose={onClose}>
      {/* Modal renders nothing while closed, so the boxes start fresh each time. */}
      <ReceiveForm onClose={onClose} {...form} />
    </Modal>
  )
}

function ReceiveForm({ delivery, loading, error, onClose, onConfirm }: Omit<ReceiveModalProps, 'open'>) {
  const owed = delivery.items.filter((l) => l.outstanding > 0)
  const [qty, setQty] = useState<Record<string, string>>(() => Object.fromEntries(owed.map((l) => [l.description, String(l.outstanding)])))
  const [note, setNote] = useState('')

  const numbers = owed.map((l) => ({ line: l, n: qty[l.description] === '' ? NaN : Number(qty[l.description]) }))
  const invalid = numbers.find(({ line, n }) => !Number.isInteger(n) || n < 0 || n > line.outstanding)
  const total = numbers.reduce((sum, { n }) => sum + (Number.isFinite(n) ? n : 0), 0)
  const everything = numbers.every(({ line, n }) => n === line.outstanding)

  function submit(event: FormEvent) {
    event.preventDefault()
    if (invalid || total === 0) return
    const items = everything ? undefined : Object.fromEntries(numbers.filter(({ n }) => n > 0).map(({ line, n }) => [line.description, n]))
    onConfirm(note.trim() || undefined, items)
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <p className="text-sm text-muted">
        Enter how many of each item actually arrived. If only part of the order came, enter less. The rest stays open and the supplier is
        chased for it.
      </p>
      <ul className="divide-y divide-line rounded-xl border border-line">
        {owed.map((l) => {
          const bad = numbers.find((x) => x.line === l)
          const wrong = !!bad && (!Number.isInteger(bad.n) || bad.n < 0 || bad.n > l.outstanding)
          return (
            <li key={l.description} className="flex items-center justify-between gap-3 px-4 py-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-title">{l.description}</p>
                <p className="text-xs text-muted">
                  {l.received > 0 ? `${l.received} already received · ` : ''}still owed {l.outstanding} of {l.ordered}
                </p>
              </div>
              <input
                type="number"
                min={0}
                max={l.outstanding}
                step={1}
                inputMode="numeric"
                aria-label={`How many ${l.description} arrived`}
                value={qty[l.description]}
                onChange={(e) => setQty((q) => ({ ...q, [l.description]: e.target.value }))}
                className={`h-11 w-24 rounded-xl border bg-white px-3 text-right text-sm font-semibold text-title focus:border-brand focus:outline-none focus:ring-4 focus:ring-brand/15 ${wrong ? 'border-danger' : 'border-line'}`}
              />
            </li>
          )
        })}
      </ul>
      <p className={`text-sm ${everything ? 'text-[#16A34A]' : 'text-amber-700'}`}>
        {invalid ? 'Each number must be a whole number, from 0 up to what is still owed.' : total === 0 ? 'Enter at least one item that arrived.'
          : everything ? 'Everything still owed arrived. This completes the delivery.' : 'Only part of the order arrived. The order stays open for the rest.'}
      </p>
      <Textarea label="Note (optional)" rows={2} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} />
      {error && <p className="text-sm text-danger">{error.message}</p>}
      <div className="flex justify-end gap-3">
        <Button type="button" variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" loading={loading} disabled={!!invalid || total === 0}>
          {everything ? 'Confirm receipt' : 'Record what arrived'}
        </Button>
      </div>
    </form>
  )
}
