import { humanize } from '@/lib/format'

/** How the agents' work is shown to a requester: plain steps, no internals (no prices, suppliers, reasons). */
export interface FlowStep {
  key: string
  label: string
  hint: string
}

export const FLOW_STEPS: FlowStep[] = [
  { key: 'received', label: 'Request received', hint: 'Your request was read and turned into an item list.' },
  { key: 'stock', label: 'Checking stock', hint: 'Seeing whether we already have it.' },
  { key: 'sourcing', label: 'Finding suppliers', hint: 'Asking suppliers for their prices.' },
  { key: 'selection', label: 'Choosing a supplier', hint: 'Comparing the quotes to pick the best one.' },
  { key: 'approval', label: 'Approval', hint: 'Making sure the order is approved.' },
  { key: 'order', label: 'Order placed', hint: 'The order is sent to the supplier.' },
  { key: 'delivery', label: 'Delivery', hint: 'Waiting for the goods to arrive.' },
]

export type StepState = 'done' | 'current' | 'pending' | 'skipped' | 'failed'
export type Outcome = 'active' | 'fulfilled' | 'delivered' | 'rejected' | 'delayed' | 'cancelled'

export interface CaseFlow {
  states: StepState[]
  outcome: Outcome
  /** One friendly sentence describing where things are right now. */
  headline: string
}

const STOCK = 1
const APPROVAL = 4

/** Where an in-progress case is: the step it is on, and what to tell the requester. */
const ACTIVE: Record<string, { current: number; headline: string; outcome?: Outcome }> = {
  created: { current: 0, headline: "We've received your request." },
  purchase_request_created: { current: 1, headline: 'Checking whether we already have this in stock.' },
  sourcing_needed: { current: 2, headline: "We don't have enough in stock, so we're asking suppliers for prices." },
  awaiting_quotes: { current: 2, headline: "We've asked suppliers for prices and are waiting for their replies." },
  sourcing_stalled: { current: 2, headline: 'This is taking longer than usual. Our team has been told and will follow up.' },
  negotiating: { current: 3, headline: 'We have the offers and are checking whether the best supplier can do better.' },
  vendor_selected: { current: 3, headline: "We've compared the quotes and chosen a supplier." },
  awaiting_approval: { current: 4, headline: "Waiting for a manager's approval." },
  approved: { current: 5, headline: 'Approved. We are placing the order.' },
  po_send_failed: { current: 5, headline: 'Approved. Our team is finishing the order with the supplier.' },
  po_failed: { current: 5, headline: 'Approved. Our team is finishing the order with the supplier.' },
  po_issued: { current: 6, headline: 'The order has been placed. Waiting for delivery.' },
  cancel_pending: { current: 5, headline: 'You cancelled this request. We have asked the supplier to cancel the order and are waiting for their answer.' },
  delivery_late: {
    current: 6,
    headline: 'Delivery is running late. Our team is following up with the supplier.',
    outcome: 'delayed',
  },
}

export function describeCase(stage: string, status: string): CaseFlow {
  const total = FLOW_STEPS.length
  const progress = (current: number): StepState[] =>
    FLOW_STEPS.map((_, i) => (i < current ? 'done' : i === current ? 'current' : 'pending'))

  if (stage === 'fulfilled_from_stock') {
    return {
      outcome: 'fulfilled',
      headline: "Good news - it's available in stock and will be dispatched to you.",
      states: FLOW_STEPS.map((_, i) => (i <= STOCK ? 'done' : 'skipped')),
    }
  }
  if (stage === 'delivered') {
    return { outcome: 'delivered', headline: 'Delivered. This request is complete.', states: Array(total).fill('done') }
  }
  if (stage === 'merged') {
    return { outcome: 'cancelled', headline: 'This request was combined with another request for the same item, so one order covers both.', states: FLOW_STEPS.map(() => 'skipped') }
  }
  if (stage === 'cancelled') {
    return { outcome: 'cancelled', headline: 'This request was cancelled.', states: FLOW_STEPS.map(() => 'skipped') }
  }
  if (stage === 'rejected') {
    return {
      outcome: 'rejected',
      headline: "This request wasn't approved. Please speak to your manager if you have questions.",
      states: FLOW_STEPS.map((_, i) => (i < APPROVAL ? 'done' : i === APPROVAL ? 'failed' : 'skipped')),
    }
  }

  const known = ACTIVE[stage]
  if (known) {
    return { outcome: known.outcome ?? 'active', headline: known.headline, states: progress(known.current) }
  }
  if (status === 'closed') {
    return { outcome: 'delivered', headline: 'This request is complete.', states: Array(total).fill('done') }
  }
  // A stage this screen doesn't know yet: stay neutral rather than guess a step.
  return { outcome: 'active', headline: 'Your request is in progress.', states: progress(1) }
}

const EVENT_LABELS: Record<string, string> = {
  'case.created': 'Request received',
  'purchase_request.created': 'Request understood and items listed',
  'stock.checked': 'Stock checked',
  'rfq.sent': 'Price requests sent to suppliers',
  'quote.submitted': 'A supplier sent a quote',
  'vendor.selected': 'Best supplier chosen',
  'approval.requested': 'Sent for manager approval',
  'approval.auto_approved': 'Approved automatically',
  'approval.approved': 'Approved by a manager',
  'approval.rejected': 'Not approved',
  'request.changed': 'The request was changed',
  'case.cancelled': 'The request was cancelled',
  'quote.revised': 'A supplier sent a revised price',
  'po.price_change_proposed': 'The supplier asked for a different price',
  'po.price_change_accepted': 'The revised price was accepted',
  'po.price_change_rejected': 'The revised price was refused',
  'po.price_lowered': 'The supplier lowered the price',
  'goods.issue_reported': 'A problem with the goods was reported to the supplier',
  'goods.issue_resolved': 'The problem with the goods was sorted out',
  'case.merged_into': 'Combined with another request for the same item',
  'email.bounced': 'An email to a supplier bounced',
  'quote.refresh_requested': 'A supplier was asked to refresh an expired quote',
  'po.cancel_requested': 'The supplier was asked to cancel the order',
  'po.cancelled': 'The order was cancelled',
  'po.cancel_withdrawn': 'The cancellation was dropped and the order carries on',
  'sourcing.restarted': 'Suppliers asked again for new prices',
  'po.issued': 'Order sent to the supplier',
  'delivery.received': 'Goods received',
  'case.closed': 'Request completed',
  'document.received': 'A document arrived',
  'document.reading': 'Reading the document',
  'document.read': 'Finished reading the document',
}

export function eventLabel(eventType: string): string {
  return EVENT_LABELS[eventType] ?? humanize(eventType)
}
