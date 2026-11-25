export interface Invoice {
  invoice_id: string
  case_id: string
  purchase_order_id: string
  vendor_id: string
  vendor_name: string
  po_number: string
  /** Filled on the Invoices page's list. */
  case_number?: string | null
  invoice_number: string | null
  total_amount: number | null
  /** What the invoice showed for tax (null when it showed none). */
  subtotal: number | null
  tax_rate_pct: number | null
  tax_amount: number | null
  /** matched | on_hold | mismatch | approved | rejected */
  status: string
  issues: string[]
  source: string
  decided_by: string | null
  decision_note: string | null
  created_at: string
  decided_at: string | null
  /** One sentence: does it match, and what to do. */
  suggestion: string | null
  /** match | waiting | mismatch | check */
  verdict: string | null
}
