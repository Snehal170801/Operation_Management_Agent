import { useState, type FormEvent } from 'react'
import { RefreshCw, XCircle } from 'lucide-react'
import clsx from 'clsx'
import { Button } from '@/components/ui/Button'
import { Textarea } from '@/components/ui/Field'
import { Modal } from '@/components/ui/Modal'

export interface RejectChoice {
  note?: string
  /** Ask the suppliers for new quotes instead of ending the request. */
  reSource: boolean
  /** With reSource: leave out the supplier who was selected this time. */
  skipSelected: boolean
}

interface RejectModalProps {
  open: boolean
  /** False once the request has been sent back as many times as allowed (or while this is not known yet). */
  canAskAgain: boolean
  /** The supplier currently selected, so the approver can leave them out of the new round. */
  selectedSupplier?: string
  loading?: boolean
  error?: Error | null
  onClose: () => void
  onConfirm: (choice: RejectChoice) => void
}

/** Rejecting is a choice: end the request for good, or send it back out so the suppliers can offer again. */
export function RejectModal({ open, onClose, ...form }: RejectModalProps) {
  return (
    <Modal open={open} title="Reject these offers?" onClose={onClose}>
      {/* Modal renders nothing while closed, so the form starts fresh each time. */}
      <RejectForm onClose={onClose} {...form} />
    </Modal>
  )
}

function Choice({ checked, onSelect, icon, title, children }: { checked: boolean; onSelect: () => void; icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <label
      className={clsx(
        'flex cursor-pointer items-start gap-3 rounded-xl border px-4 py-3 transition-colors',
        checked ? 'border-brand bg-brand-tint ring-4 ring-brand/10' : 'border-line bg-white hover:bg-brand-tint/50',
      )}
    >
      <input type="radio" name="reject-choice" checked={checked} onChange={onSelect} className="mt-1 accent-[#c53536]" />
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2 text-sm font-semibold text-title">
          {icon} {title}
        </span>
        <span className="mt-0.5 block text-xs leading-relaxed text-muted">{children}</span>
      </span>
    </label>
  )
}

function RejectForm({ canAskAgain, selectedSupplier, loading, error, onClose, onConfirm }: Omit<RejectModalProps, 'open'>) {
  const [again, setAgain] = useState(canAskAgain)
  const [skip, setSkip] = useState(false)
  const [note, setNote] = useState('')
  const asking = again && canAskAgain

  function submit(event: FormEvent) {
    event.preventDefault()
    onConfirm({ note: note.trim() || undefined, reSource: asking, skipSelected: asking && skip })
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <div className="flex flex-col gap-2.5">
        {canAskAgain && (
          <Choice checked={again} onSelect={() => setAgain(true)} icon={<RefreshCw size={15} className="text-brand-ink" />} title="Ask the suppliers for new quotes">
            Every supplier gets a fresh request and a new deadline. The offers so far are set aside (kept on record) and the request carries on automatically when the new ones arrive.
          </Choice>
        )}
        <Choice checked={!asking} onSelect={() => setAgain(false)} icon={<XCircle size={15} className="text-danger" />} title="Reject for good">
          The request is closed as not approved and no order is placed.
        </Choice>
        {!canAskAgain && <p className="text-xs text-muted">This request has already been sent back for new quotes as many times as is allowed.</p>}
      </div>

      {asking && selectedSupplier && (
        <label className="flex items-center gap-2 text-sm text-title">
          <input type="checkbox" checked={skip} onChange={(e) => setSkip(e.target.checked)} className="accent-[#c53536]" />
          Don't ask {selectedSupplier} again
        </label>
      )}

      <Textarea label={asking ? 'Why? (the suppliers do not see this)' : 'Note (optional)'} rows={3} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} />
      {error && <p className="text-sm text-danger">{error.message}</p>}
      <div className="flex justify-end gap-3">
        <Button type="button" variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" loading={loading} className={asking ? undefined : 'bg-none! bg-danger!'}>
          {asking ? 'Reject and ask again' : 'Reject for good'}
        </Button>
      </div>
    </form>
  )
}
