export interface PurchaseRequestItem {
  description: string
  quantity: number
}

export interface PurchaseRequest {
  purchase_request_id: string
  case_id: string
  cost_center: string | null
  raw_request: string
  items: PurchaseRequestItem[]
  created_at: string
  needed_by?: string | null
  urgent?: boolean
}
