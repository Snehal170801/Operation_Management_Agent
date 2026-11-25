import { useState, type FormEvent } from 'react'
import { AlertTriangle, Check, CheckCircle2, Clock, FilePlus2, HelpCircle, X, type LucideIcon } from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { Textarea } from '@/components/ui/Field'
import { Modal } from '@/components/ui/Modal'
import { NoteModal } from '@/components/ui/NoteModal'
import { QueryState } from '@/components/ui/QueryState'
import { useAuth } from '@/features/auth/AuthContext'
import { formatAmount, formatDateTime } from '@/lib/format'
import { useCaseInvoices, useDecideInvoice, useSubmitInvoice } from '../hooks'
import type { Invoice } from '../types'

const VERDICT: Record<string, { Icon: LucideIcon; tone: string }> = {
  match: { Icon: CheckCircle2, tone: 'bg-emerald-50 text-emerald-900' },
  waiting: { Icon: Clock, tone: 'bg-amber-50 text-amber-900' },
  mismatch: { Icon: AlertTriangle, tone: 'bg-danger-soft text-danger' },
  check: { Icon: HelpCircle, tone: 'bg-amber-50 text-amber-900' },
}

/** Invoices for a case: matched automatically, held until the goods arrive, or flagged for a person. */
export function InvoiceCard({ caseId }: { caseId: string }) {
  const { can } = useAuth()
  const invoices = useCaseInvoices(caseId)
  const [adding, setAdding] = useState(false)

  return (
    <Card
      title="Invoices"
      className="lg:col-span-2"
      action={
        can('invoices:decide') ? (
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="inline-flex items-center gap-1 font-medium text-brand-ink hover:underline"
          >
            <FilePlus2 size={14} /> Add invoice text
          </button>
        ) : undefined
      }
    >
      <QueryState
        variant="list" rows={2}
        isLoading={invoices.isLoading}
        error={invoices.error}
        isEmpty={!invoices.data?.length}
        emptyMessage="No invoice yet. When the vendor emails one it is read and matched automatically."
      >
        <ul className="flex flex-col gap-4">
          {invoices.data?.map((inv) => (
            <InvoiceRow key={inv.invoice_id} invoice={inv} />
          ))}
        </ul>
      </QueryState>
      <AddInvoiceModal caseId={caseId} open={adding} onClose={() => setAdding(false)} />
    </Card>
  )
}

function InvoiceRow({ invoice }: { invoice: Invoice }) {
  const { can } = useAuth()
  const decide = useDecideInvoice()
  const [mode, setMode] = useState<'approve' | 'reject' | null>(null)
  // A matching invoice that is only waiting for the goods has nothing to decide: it clears by itself, so offering
  // "Approve anyway" there would only invite skipping the goods check.
  const open = (invoice.status === 'mismatch' || invoice.status === 'on_hold') && invoice.verdict !== 'waiting'

  function close() {
    setMode(null)
    decide.reset()
  }

  return (
    <li className="flex flex-col gap-2 rounded-xl border border-line px-4 py-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium text-title">
          {invoice.invoice_number ?? 'Unreadable number'} · {formatAmount(invoice.total_amount)}
        </span>
        <Badge value={invoice.status} />
      </div>
      {invoice.tax_amount !== null && (
        <p className="text-xs text-muted">
          Tax shown: {formatAmount(invoice.tax_amount)}
          {invoice.tax_rate_pct !== null ? ` (${invoice.tax_rate_pct}%)` : ''}
          {invoice.subtotal !== null ? ` on ${formatAmount(invoice.subtotal)}` : ''}
        </p>
      )}
      <p className="text-xs text-muted">
        {invoice.vendor_name} · for {invoice.po_number} · {formatDateTime(invoice.created_at)} ·{' '}
        {invoice.source === 'email' ? 'received by email' : 'added by hand'}
      </p>

      {invoice.suggestion && invoice.verdict && (
        <p className={'flex items-start gap-2 rounded-lg px-3 py-2.5 text-sm font-medium ' + (VERDICT[invoice.verdict]?.tone ?? '')}>
          {(() => {
            const Icon = VERDICT[invoice.verdict]?.Icon ?? HelpCircle
            return <Icon size={17} className="mt-0.5 shrink-0" />
          })()}
          <span>{invoice.suggestion}</span>
        </p>
      )}

      {invoice.issues.length > 0 && invoice.status !== 'on_hold' && (
        <div
          className={
            'flex items-start gap-2 rounded-lg px-3 py-2 text-xs ' +
            (invoice.status === 'mismatch' ? 'bg-danger-soft text-danger' : 'bg-brand-tint text-muted')
          }
        >
          {invoice.status === 'mismatch' && <AlertTriangle size={15} className="mt-0.5 shrink-0" />}
          <ul className="list-disc pl-4">
            {invoice.issues.map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
        </div>
      )}
      {invoice.status === 'matched' && (
        <p className="text-xs text-muted">Matched the purchase order and the goods received - cleared automatically.</p>
      )}
      {invoice.decided_by && (
        <p className="text-xs text-muted">
          {invoice.status === 'approved' ? 'Approved' : 'Rejected'} by {invoice.decided_by}
          {invoice.decision_note ? ` - “${invoice.decision_note}”` : ''}
        </p>
      )}

      {open && can('invoices:decide') && (
        <div className="flex gap-2">
          <Button className="h-9 px-3" onClick={() => setMode('approve')}>
            <Check size={16} /> Approve anyway
          </Button>
          <Button variant="secondary" className="h-9 px-3" onClick={() => setMode('reject')}>
            <X size={16} /> Reject
          </Button>
        </div>
      )}

      <NoteModal
        open={mode !== null}
        title={mode === 'approve' ? 'Clear this invoice for payment?' : 'Reject this invoice?'}
        description={
          mode === 'approve'
            ? 'You are accepting it even though it did not fully match. If the goods are received, the case will close.'
            : 'The invoice will not be paid. Ask the vendor for a corrected one.'
        }
        confirmLabel={mode === 'approve' ? 'Approve' : 'Reject'}
        danger={mode === 'reject'}
        loading={decide.isPending}
        error={decide.error}
        onClose={close}
        onConfirm={(note) =>
          decide.mutate({ invoiceId: invoice.invoice_id, approve: mode === 'approve', note }, { onSuccess: close })
        }
      />
    </li>
  )
}

function AddInvoiceModal({ caseId, open, onClose }: { caseId: string; open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} title="Add invoice text" onClose={onClose}>
      <AddInvoiceForm caseId={caseId} onClose={onClose} />
    </Modal>
  )
}

function AddInvoiceForm({ caseId, onClose }: { caseId: string; onClose: () => void }) {
  const [text, setText] = useState('')
  const submit = useSubmitInvoice(caseId)

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    submit.mutate(text.trim(), { onSuccess: onClose })
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      <p className="text-sm text-muted">
        Paste the text of the vendor&apos;s invoice (for example copied from their email, or from a PDF). The agent will
        read and match it. Emailed invoices are read automatically - this is for ones that arrive another way.
      </p>
      <Textarea
        label="Invoice text"
        required
        rows={8}
        maxLength={8000}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      {submit.error && <p className="text-sm text-danger">{submit.error.message}</p>}
      <div className="flex justify-end gap-3">
        <Button type="button" variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" loading={submit.isPending} disabled={!text.trim()}>
          Read and match
        </Button>
      </div>
    </form>
  )
}
