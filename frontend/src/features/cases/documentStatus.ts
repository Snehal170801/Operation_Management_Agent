import type { CaseEvent } from './types'

export type DocumentState = 'reading' | 'matched' | 'needs_person' | 'other'
export interface DocumentStatus {
  state: DocumentState
  files: string[]
  reason: string | null
}

/** "Reading" for longer than this means the read died without saying so; shown as needing a person (same rule as the server). */
const STUCK_AFTER_MS = 180_000

/** Where the latest supplier document is: received -> reading -> matched / needs a person. Same rule as backend core/document_status.py. */
export function documentStatus(events: CaseEvent[] | undefined, now = Date.now()): DocumentStatus | null {
  const last = [...(events ?? [])].reverse().find((e) => e.event_type === 'document.received' || e.event_type === 'document.reading' || e.event_type === 'document.read')
  if (!last) return null
  const payload = (last.payload && typeof last.payload === 'object' ? last.payload : {}) as { files?: string[]; outcome?: string; reason?: string | null }
  const files = payload.files ?? []
  if (last.event_type === 'document.read') {
    const state = payload.outcome === 'matched' || payload.outcome === 'other' ? payload.outcome : 'needs_person'
    return { state, files, reason: payload.reason ?? null }
  }
  if (now - new Date(last.created_at).getTime() > STUCK_AFTER_MS) return { state: 'needs_person', files, reason: 'Reading took too long.' }
  return { state: 'reading', files, reason: null }
}
