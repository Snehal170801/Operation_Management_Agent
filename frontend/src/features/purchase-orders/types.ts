export interface PurchaseOrderItem {
  description: string
  quantity: number
}

/** One row of the Purchase orders page. */
export interface PurchaseOrderListItem {
  purchase_order_id: string
  po_number: string
  case_id: string
  case_number: string | null
  vendor_name: string
  total_amount: number | null
  tax_amount: number | null
  total_with_tax: number | null
  status: string
  delivery_status: string | null
  expected_delivery_date: string | null
  created_at: string
  sent_at: string | null
  acknowledged_at: string | null
  delivered_at: string | null
}

export interface PurchaseOrder {
  purchase_order_id: string
  po_number: string
  case_id: string
  vendor_id: string
  vendor_name: string
  total_amount: number | null
  /** Tax lines, when a tax rate is set (null otherwise). */
  tax_rate_pct: number | null
  tax_amount: number | null
  total_with_tax: number | null
  lead_time_days: number | null
  terms: string | null
  expected_delivery_date: string | null
  items: PurchaseOrderItem[]
  /** issued | sent | send_failed */
  status: string
  created_at: string
  sent_at: string | null
  /** When the supplier confirmed they have the order (null while they have not). */
  acknowledged_at: string | null
  /** The supplier's address, or the person who confirmed it another way. */
  acknowledged_by: string | null
  /** How many times the supplier has been asked to confirm. */
  confirm_chase_count: number
  last_confirm_chase_at: string | null
  /** Set once the supplier was asked enough times with no answer and a person was told. */
  confirm_escalated_at: string | null
  /** What the supplier said was wrong with the order, until a person sorts it out. */
  vendor_issue: string | null
  /** The requester cancelled, so the supplier was asked to cancel this order. */
  cancel_requested_at: string | null
  cancel_requested_by: string | null
  cancel_reason: string | null
  cancel_chase_count: number
  cancel_escalated_at: string | null
  cancel_refused_at: string | null
}
