export interface WorkItem {
  id: string
  title: string
  /** Why it is waiting. */
  detail: string
  /** An in-app path to open. */
  link: string
  action: string
  urgent: boolean
  since: string | null
  /** When the admin is told if nobody acts (only for work the escalation rule covers). */
  escalates_at: string | null
  /** A caution, e.g. "you asked for this, so someone else has to approve it". */
  note: string | null
}

export interface HandledItem {
  id: string
  title: string
  /** What was done, e.g. "Approved". */
  what: string
  /** Who did it. */
  by: string
  at: string
  link: string
}

export interface WorkQueue {
  key: string
  title: string
  agent: string
  /** What to say when nothing is waiting. */
  empty: string
  items: WorkItem[]
  /** What the team finished recently. */
  handled: HandledItem[]
}

export interface MyWork {
  total: number
  queues: WorkQueue[]
}
