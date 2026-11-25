/** What an agent is doing for one case. Worked out by the server (app/core/agent_flow.py). */
export type AgentState =
  | 'pending' // not reached yet
  | 'working' // a step is running right now
  | 'waiting' // did its part, waiting on suppliers / goods / an invoice
  | 'needs_person' // blocked until a person decides or fixes something
  | 'done'
  | 'skipped' // not needed for this case
  | 'stopped' // the case ended here (a rejected approval)
  | 'failed'

export type AgentKey = 'purchase' | 'procurement' | 'vendor' | 'approval' | 'po' | 'delivery' | 'invoice'

export interface AgentNode {
  key: AgentKey
  name: string
  role: string
  state: AgentState
  /** What it is doing / did / will do, in plain words. */
  label: string
  progress: { done: number; total: number; text: string | null } | null
  started_at: string | null
  finished_at: string | null
  seconds: number | null
  runs: number
  /** Staff only. */
  detail: string | null
  error: string | null
}

export type FlowOutcome = 'active' | 'needs_person' | 'completed' | 'fulfilled' | 'rejected' | 'cancelled' | 'merged'

export interface FlowActivity {
  id: number
  at: string
  agent: string
  text: string
  tone: 'info' | 'ok' | 'warn' | 'bad'
}

export interface RequestDetails {
  raw_text: string
  items: { description: string; quantity: number }[]
  cost_center: string | null
  submitted_at: string | null
  /** Staff only. */
  requested_by: string | null
}

/** One block of an agent's detail view. `items` depends on `kind`: facts {label,value} · checks {label,status,detail} · timeline {at,text,tone}. */
export interface InfoSection {
  title: string
  kind: 'facts' | 'text' | 'table' | 'checks' | 'timeline'
  items: Record<string, string | null>[]
  body: string | null
  columns: string[]
  rows: string[][]
  highlight: number | null
}

export interface AgentInfo {
  key: string
  name: string
  role: string
  audience: 'requester' | 'staff'
  sections: InfoSection[]
}

export interface SupportAgent {
  key: 'operations' | 'notification'
  name: string
  role: string
  state: 'idle' | 'active' | 'done' | 'attention'
  label: string
}

export interface AgentFlowState {
  case_id: string
  case_number: string | null
  stage: string
  status: string
  outcome: FlowOutcome
  headline: string
  /** What happens after the part under way now; null once finished. */
  next_step: string | null
  support: SupportAgent[]
  /** When the goods are due (a date), once an order exists. */
  expected_delivery: string | null
  active_agent: string | null
  needs_person: boolean
  agents: AgentNode[]
  /** The latest things that happened, newest first. */
  activity: FlowActivity[]
  generated_at: string
  audience: 'requester' | 'staff'
  request: RequestDetails | null
}

export interface AgentFlowCase {
  case_id: string
  case_number: string | null
  items_summary: string | null
  stage: string
  status: string
  active: boolean
  headline: string
  updated_at: string
  /** Staff only: who asked. */
  requester: string | null
}

export interface BoardCase {
  case_id: string
  case_number: string | null
  items_summary: string | null
  requester: string | null
  state: AgentState
  label: string
  progress: { done: number; total: number; text: string | null } | null
}

export interface BoardFeedItem {
  id: number
  at: string
  case_id: string
  case_number: string | null
  agent: string
  text: string
  tone: 'info' | 'ok' | 'warn' | 'bad'
}

export interface BoardAgent {
  key: AgentKey
  name: string
  role: string
  working: number
  waiting: number
  needs_person: number
  /** What the first working case is being done right now. */
  now_doing: string | null
  cases: BoardCase[]
  /** Cases beyond the ones listed. */
  more: number
}

export interface AgentBoard {
  generated_at: string
  open_cases: number
  working_now: number
  needs_person: number
  agents: BoardAgent[]
  /** The latest things the agents did, across every case. */
  feed: BoardFeedItem[]
}

export interface ReplayFrame {
  at: string
  headline: string
  next_step: string | null
  support: SupportAgent[]
  outcome: FlowOutcome
  agents: AgentNode[]
  /** What happened at this moment. */
  event: FlowActivity | null
}

export interface AgentReplay {
  case_id: string
  case_number: string | null
  audience: 'requester' | 'staff'
  frames: ReplayFrame[]
  request: RequestDetails | null
  expected_delivery: string | null
}
