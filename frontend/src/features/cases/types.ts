export interface CreateCaseRequest {
  /** Staff only: file on someone's behalf. Requesters always file as themselves. */
  requester_id?: string
  raw_request: string
  /** When the goods are needed by (YYYY-MM-DD), and whether it is urgent. */
  needed_by?: string
  urgent?: boolean
}

export interface CreateCaseResponse {
  case_id: string
}

export interface CaseStatus {
  case_id: string
  /** Readable number, e.g. REQ-2026-0007. */
  case_number: string | null
  requester_id: string
  stage: string
  status: string
  summary: string | null
  created_at: string
  updated_at: string
}

export interface CaseListItem {
  case_id: string
  case_number: string | null
  requester_id: string
  stage: string
  status: string
  item_count: number | null
  total_quantity: number | null
  items_summary: string | null
  urgent?: boolean
  needed_by?: string | null
  created_at: string
  updated_at: string
}

export interface CaseEvent {
  event_id: number
  event_type: string
  agent_name: string | null
  payload: unknown
  /** Plain-English line for staff (null for a requester, who gets the page's own wording). */
  label?: string | null
  created_at: string
}
