export interface Delivery {
  case_id: string
  po_number: string
  vendor_name: string
  expected_delivery_date: string | null
  /** pending | delivered */
  delivery_status: string
  delivered_at: string | null
  received_by: string | null
  delivery_note: string | null
  chase_count: number
  last_chased_at: string | null
  escalated_at: string | null
  /** One line per ordered item. */
  items: { description: string; ordered: number; received: number; outstanding: number }[]
  batches: { at: string | null; by: string | null; note: string | null; items: Record<string, number> }[]
  received_units: number
  ordered_units: number
  /** Some, but not all, of the order has arrived. */
  partial: boolean
  /** Set when a person accepted that the rest will not come. */
  short_closed_at: string | null
}
