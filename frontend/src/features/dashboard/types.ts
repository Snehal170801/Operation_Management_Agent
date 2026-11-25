import type { AppNotification } from '@/features/notifications/hooks'

export interface DashboardTotals {
  cases_total: number
  cases_open: number
  cases_closed: number
  pending_approvals: number
  needs_attention: number
  stock_items: number
  low_stock: number
  out_of_stock: number
  suppliers: number
  purchase_orders: number
  awaiting_delivery: number
  overdue_deliveries: number
  invoices_to_review: number
}

export interface DashboardSnapshot {
  generated_at: string
  automation_paused: boolean
  totals: DashboardTotals
  by_stage: { stage: string; count: number }[]
  /** Always 7 entries, oldest first, with 0 on quiet days. */
  created_per_day: { day: string; count: number }[]
  activity: { event_id: number; case_id: string; case_number: string | null; event_type: string; agent_name: string | null; created_at: string }[]
  attention: AppNotification[]
  spend: { ordered_total: number; ordered_today: number; auto_approved_today: number; daily_limit: number }
  rates: { auto_approval_percent: number | null; avg_close_minutes: number | null }
}
