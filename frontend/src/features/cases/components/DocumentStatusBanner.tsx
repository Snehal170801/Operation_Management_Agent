import { CheckCircle2, FileSearch, Loader2, TriangleAlert } from 'lucide-react'
import type { CaseEvent } from '../types'
import { documentStatus } from '../documentStatus'

/** The live status of the latest supplier document. The case page already refreshes itself when something changes, so this updates
 * without a reload. `staff` shows file names and the reason; a requester sees only the plain state (the server sends them no detail). */
export function DocumentStatusBanner({ events, staff }: { events: CaseEvent[] | undefined; staff: boolean }) {
  const status = documentStatus(events)
  if (!status) return null
  const names = staff && status.files.length ? ` (${status.files.join(', ')})` : ''
  const view = {
    reading: { icon: <Loader2 size={16} className="animate-spin" />, text: `Reading the document${names}…`, tone: 'text-brand-ink bg-brand-tint' },
    matched: { icon: <CheckCircle2 size={16} />, text: `Document read and matched${names}.`, tone: 'text-emerald-700 bg-emerald-50' },
    other: { icon: <FileSearch size={16} />, text: `Document read${names}. Nothing to match.`, tone: 'text-muted bg-page' },
    needs_person: {
      icon: <TriangleAlert size={16} />,
      text: staff ? `A person needs to look at the document${names}.${status.reason ? ` ${status.reason}` : ''}` : 'Our team is looking at a document that needs a person.',
      tone: 'text-danger bg-danger-soft',
    },
  }[status.state]
  return (
    <div role="status" aria-live="polite" className={`flex items-start gap-2 rounded-xl px-4 py-3 text-sm font-medium ${view.tone}`}>
      <span className="mt-0.5 shrink-0">{view.icon}</span>
      <span>{view.text}</span>
    </div>
  )
}
