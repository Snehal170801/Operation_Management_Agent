import { Siren } from 'lucide-react'
import { formatDate } from '@/lib/format'

/** A small red "URGENT" tag, with the date the goods are needed by when there is one. */
export function UrgentBadge({ neededBy }: { neededBy?: string | null }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-danger-soft px-2 py-0.5 align-middle text-[11px] font-semibold text-danger">
      <Siren size={11} /> URGENT{neededBy ? ` · by ${formatDate(neededBy)}` : ''}
    </span>
  )
}
