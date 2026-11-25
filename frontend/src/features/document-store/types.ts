export type DocumentKind = 'purchase_order' | 'invoice' | 'quote' | 'file'

export interface StoredDocument {
  id: string
  kind: DocumentKind
  kind_label: string
  title: string
  case_id: string
  case_number: string | null
  /** Null for a requester (they only see that a document exists). */
  vendor: string | null
  amount: number | null
  status: string | null
  at: string | null
}

export interface DocumentPage {
  items: StoredDocument[]
  total: number
  /** Matches per kind, ignoring the kind filter (for the tabs). */
  counts: Record<DocumentKind, number>
  limit: number
  offset: number
  /** True for a requester: only their own cases, only "there is an order / an invoice". */
  sanitised: boolean
}
