export interface ReportTotals {
  requests: number
  completed: number
  from_stock: number
  rejected: number
  cancelled: number
  in_progress: number
  spend: number
  orders: number
  avg_cycle_hours: number | null
}

export interface AgentTrouble {
  agent: string
  cases: number
  reasons: { label: string; cases: number }[]
}

export interface ReportAutomation {
  touchless: number
  needed_a_person: number
  in_progress_so_far_clean: number
  touchless_pct: number | null
  by_agent: AgentTrouble[]
}

export interface ReportSpend {
  total: number
  orders: number
  by_vendor: { vendor: string; total: number; orders: number }[]
  by_month: { month: string; total: number; orders: number }[]
}

export interface StageTime {
  label: string
  avg_hours: number | null
  count: number
}

export interface StuckStage {
  stage: string
  label: string
  count: number
  oldest_hours: number
  avg_hours: number
}

export interface SupplierScore {
  vendor_id: string
  name: string
  asked: number
  replied: number
  reply_rate: number | null
  avg_reply_hours: number | null
  orders: number
  spend: number
  confirm_rate: number | null
  avg_confirm_hours: number | null
  delivered: number
  late: number
  avg_days_late: number | null
  invoices: number
  invoice_problems: number
}

export interface Report {
  days: number
  generated_at: string
  totals: ReportTotals
  automation: ReportAutomation
  spend: ReportSpend
  stage_times: StageTime[]
  stuck: StuckStage[]
  suppliers: SupplierScore[]
}
