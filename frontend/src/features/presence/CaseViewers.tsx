import { useEffect, useState } from 'react'
import { Eye } from 'lucide-react'
import { api } from '@/lib/api-client'

const EVERY_MS = 20_000

/** Tells the server "I have this case open" every 20 s while the tab is visible, and returns who else has it open. */
function useOtherViewers(caseId: string): string[] {
  const [others, setOthers] = useState<string[]>([])

  useEffect(() => {
    if (!caseId) return
    let stopped = false
    const checkIn = async () => {
      if (document.hidden) return // a tab nobody is looking at is not "looking"
      try {
        const reply = await api.post<{ others: string[] }>(`/presence/cases/${caseId}`, {})
        if (!stopped) setOthers(reply.others)
      } catch {
        if (!stopped) setOthers([]) // never let this get in the way of the page
      }
    }
    void checkIn()
    const timer = setInterval(() => void checkIn(), EVERY_MS)
    document.addEventListener('visibilitychange', checkIn)
    return () => {
      stopped = true
      clearInterval(timer)
      document.removeEventListener('visibilitychange', checkIn)
      void api.delete(`/presence/cases/${caseId}`).catch(() => undefined)
    }
  }, [caseId])

  return others
}

/** "Priya is also looking at this case": a warning so two people don't both act on it. Shows nothing when alone. */
export function CaseViewers({ caseId }: { caseId: string }) {
  const others = useOtherViewers(caseId)
  if (!others.length) return null
  const names = others.map((o) => o.split('@')[0])
  const text = names.length === 1 ? `${names[0]} is also looking at this case` : `${names.slice(0, -1).join(', ')} and ${names.at(-1)} are also looking at this case`
  return (
    <p role="status" className="mb-3 inline-flex items-center gap-2 self-start rounded-full bg-amber-100 px-3.5 py-1.5 text-sm font-medium text-amber-900">
      <Eye size={15} aria-hidden /> {text}. Check before you act on it.
    </p>
  )
}
