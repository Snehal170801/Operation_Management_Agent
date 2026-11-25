import { useState, type FormEvent } from 'react'
import { Button } from '@/components/ui/Button'
import { useConfirm } from '@/components/ui/confirm-context'
import { Textarea } from '@/components/ui/Field'
import { Modal } from '@/components/ui/Modal'
import { useSubmitQuote } from '../hooks'

interface Supplier {
  vendor_id: string
  name: string
}

interface Props {
  caseId: string
  open: boolean
  /** Only suppliers who were asked for a quote on this case. */
  suppliers: Supplier[]
  onClose: () => void
}

export function AddQuoteModal({ caseId, open, suppliers, onClose }: Props) {
  return (
    <Modal open={open} title="Add a quote by hand" onClose={onClose}>
      {/* Modal renders nothing while closed, so the form starts empty every time. */}
      <AddQuoteForm caseId={caseId} suppliers={suppliers} onClose={onClose} />
    </Modal>
  )
}

function AddQuoteForm({ caseId, suppliers, onClose }: Omit<Props, 'open'>) {
  const [vendorId, setVendorId] = useState(suppliers[0]?.vendor_id ?? '')
  const [text, setText] = useState('')
  const submit = useSubmitQuote(caseId)
  const confirm = useConfirm()

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    const supplier = suppliers.find((s) => s.vendor_id === vendorId)?.name ?? 'this supplier'
    const ok = await confirm({
      title: 'Add this quote?',
      message: `It will be recorded as ${supplier}'s quote. The agent reads the price, delivery time and terms from the text you typed.`,
      confirmLabel: 'Add quote',
    })
    if (!ok) return
    submit.mutate({ vendor_id: vendorId, raw_quote_text: text.trim() }, { onSuccess: onClose })
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      <p className="text-sm text-muted">
        Use this when a supplier gives you a price another way (a phone call, a message). Type what they said; the agent
        reads the price, delivery time and terms from it, just like an emailed quote.
      </p>
      <label className="flex flex-col gap-1.5 text-xs font-medium text-muted">
        Supplier
        <select
          value={vendorId}
          onChange={(e) => setVendorId(e.target.value)}
          className="h-11 rounded-xl border border-line bg-white px-3 text-sm text-title focus:border-brand focus:outline-none"
        >
          {suppliers.map((s) => (
            <option key={s.vendor_id} value={s.vendor_id}>
              {s.name}
            </option>
          ))}
        </select>
      </label>
      <Textarea
        label="Their quote"
        required
        rows={4}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="e.g. Total Rs 42,000. Delivery 7 days. Terms: 50% advance"
      />
      {submit.error && <p className="text-sm text-danger">{submit.error.message}</p>}
      <div className="flex justify-end gap-3">
        <Button type="button" variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" loading={submit.isPending} disabled={!text.trim() || !vendorId}>
          Save quote
        </Button>
      </div>
    </form>
  )
}
