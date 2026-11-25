import { Siren } from 'lucide-react'

interface UrgencyFieldsProps {
  neededBy: string
  urgent: boolean
  onNeededBy: (value: string) => void
  onUrgent: (value: boolean) => void
}

const today = () => {
  const d = new Date()
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 10)
}

/** Optional: when the goods are needed by, and a tick for "urgent". The agents chase an urgent request harder. */
export function UrgencyFields({ neededBy, urgent, onNeededBy, onUrgent }: UrgencyFieldsProps) {
  return (
    <div className="flex flex-wrap items-end gap-x-6 gap-y-3 rounded-xl border border-line bg-brand-tint/40 px-4 py-3">
      <label className="flex flex-col gap-1.5 text-xs font-medium text-muted">
        Needed by (optional)
        <input
          type="date"
          min={today()}
          value={neededBy}
          onChange={(e) => onNeededBy(e.target.value)}
          className="h-11 rounded-xl border border-line bg-white px-3 text-sm text-title focus:border-brand focus:outline-none focus:ring-4 focus:ring-brand/15"
        />
      </label>
      <label className="flex h-11 cursor-pointer items-center gap-2 text-sm font-medium text-title">
        <input type="checkbox" checked={urgent} onChange={(e) => onUrgent(e.target.checked)} className="h-4 w-4 accent-[#c53536]" />
        <Siren size={16} className="text-brand-ink" /> This is urgent
      </label>
      <p className="basis-full text-xs text-muted">
        An urgent request gives suppliers less time to quote, is followed up sooner, and is marked for the approver. You can also just write it in
        your request, for example “needed by Friday”.
      </p>
    </div>
  )
}
