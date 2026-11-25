export interface Approval {
  approval_id: string
  case_id: string
  case_number: string | null
  approval_type: string
  /** pending | approved | rejected | auto_approved | superseded */
  status: string
  reasons: string[]
  decided_by: string | null
  decision_note: string | null
  created_at: string
  decided_at: string | null
}

/** One supplier as the approver sees it. */
export interface ReviewOption {
  /** Place in the AI's ranking (1 = best); null if the AI gave none. */
  rank: number | null
  vendor_id: string
  vendor_name: string
  email: string | null
  price: number | null
  lead_time_days: number | null
  terms: string | null
  reliability: number | null
  /** What the supplier wrote, in their own words. */
  reply_text: string
  /** The AI's reason for this place in the ranking. */
  reason: string | null
  /** AI's pick, Cheapest, Fastest. */
  tags: string[]
}

/** A supplier asking for a higher price on an order already placed. */
export interface PriceChange {
  po_number: string | null
  vendor_name: string | null
  agreed_total: number | null
  new_total: number | null
  pct: number | null
  reply_text: string
}

export interface ApprovalReview {
  /** vendor_selection | price_change */
  kind: 'vendor_selection' | 'price_change'
  price_change: PriceChange | null
  approval_id: string
  case_id: string
  case_number: string | null
  status: string
  reasons: string[]
  requested_by: string | null
  request_text: string | null
  items: { description: string; quantity: number }[]
  recommended_vendor_id: string | null
  selected_vendor_id: string | null
  rationale: string | null
  /** One sentence: what to do, and what the other suppliers offer. */
  suggestion: string | null
  /** The supplier was asked once for a better price: what came of it (null when never asked). */
  negotiation: { vendor: string; outcome: 'waiting' | 'improved' | 'kept' | 'no_reply'; original_price: number | null; new_price: number | null; saving: number | null; text: string } | null
  options: ReviewOption[]
  /** 1 for the first set of quotes, 2 after the suppliers were asked again, and so on. */
  round: number
  /** Why an earlier round was turned down. */
  earlier_note: string | null
  /** False once the request has been sent back as many times as is allowed. */
  can_ask_again: boolean
  urgent: boolean
  needed_by: string | null
}
