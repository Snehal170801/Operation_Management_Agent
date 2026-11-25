/** Case stages that need a person, and what to tell them. Everything else the agents handle alone. */
export interface Attention {
  message: string
  /** Where to send the person: the approvals queue, or the case itself. */
  to: 'approvals' | 'case'
}

const ATTENTION: Record<string, Attention> = {
  awaiting_approval: { message: 'Waiting for your approval - something was unusual.', to: 'approvals' },
  sourcing_stalled: { message: 'No supplier quotes came in. Follow up with suppliers.', to: 'case' },
  po_send_failed: { message: 'The purchase order could not be emailed. Fix the vendor email and retry.', to: 'case' },
  po_failed: { message: 'The purchase order could not be created automatically.', to: 'case' },
  delivery_late: { message: 'Delivery is overdue and the vendor has not responded. Contact them.', to: 'case' },
}

export function attentionForInvoice(invoiceNumber: string | null, vendor: string): Attention {
  return {
    message: `Invoice ${invoiceNumber ?? '(unreadable number)'} from ${vendor} does not match the order. Review it.`,
    to: 'case',
  }
}

export function attentionFor(stage: string): Attention | null {
  return ATTENTION[stage] ?? null
}
