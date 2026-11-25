import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Merge } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { Modal } from '@/components/ui/Modal'
import { useAuth } from '@/features/auth/AuthContext'
import { api } from '@/lib/api-client'

interface Suggestion {
  keep_case_id: string
  keep_number: string | null
  fold_case_id: string
  fold_number: string | null
  matches: { item: string; primary_qty: number; secondary_qty: number }[]
  since: string
}

const key = (caseId: string) => ['combine', caseId]

/** Two requests for the same item while suppliers are still being asked: offer one combined order. A person decides. */
export function CombinePanel({ caseId }: { caseId: string }) {
  const { can } = useAuth()
  const queryClient = useQueryClient()
  const list = useQuery({ queryKey: key(caseId), queryFn: () => api.get<Suggestion[]>(`/cases/${caseId}/combine`), enabled: can('vendors:read') })
  const refresh = () => {
    for (const k of ['combine', 'cases', 'agent-flow', 'my-work', 'vendors', 'purchase-request']) void queryClient.invalidateQueries({ queryKey: [k] })
  }
  const combine = useMutation({ mutationFn: (s: Suggestion) => api.post(`/cases/${caseId}/combine`, { other_case_id: s.keep_case_id === caseId ? s.fold_case_id : s.keep_case_id }), onSuccess: refresh })
  const dismiss = useMutation({ mutationFn: (s: Suggestion) => api.post(`/cases/${caseId}/combine/dismiss`, { other_case_id: s.keep_case_id === caseId ? s.fold_case_id : s.keep_case_id }), onSuccess: refresh })
  const [asking, setAsking] = useState<Suggestion>()

  const suggestions = list.data ?? []
  if (suggestions.length === 0) return null

  return (
    <Card title="Same item, another request" action="suggestion">
      <ul className="flex flex-col gap-4 text-sm">
        {suggestions.map((s) => {
          const other = s.keep_case_id === caseId ? { id: s.fold_case_id, number: s.fold_number } : { id: s.keep_case_id, number: s.keep_number }
          const m = s.matches[0]
          return (
            <li key={`${s.keep_case_id}-${s.fold_case_id}`} className="flex flex-col gap-2">
              <p className="text-title">
                <Link to={`/cases/${other.id}`} className="font-semibold text-brand-ink hover:underline">{other.number ?? 'Another request'}</Link>
                {' '}also asks for {m ? <b>{m.item}</b> : 'the same item'}
                {m ? ` (${m.primary_qty} on ${s.keep_number ?? 'the older request'}, ${m.secondary_qty} on ${s.fold_number ?? 'the newer one'})` : ''}.
              </p>
              <p className="text-xs text-muted">
                Combined, suppliers are asked once for the total quantity (usually a better price and one delivery). The older request carries on and the
                newer one is closed as combined. Both requesters are kept informed.
              </p>
              {can('vendors:write') && (
                <div className="flex flex-wrap gap-3">
                  <Button onClick={() => setAsking(s)}>
                    <Merge size={16} /> Combine into one order
                  </Button>
                  <Button variant="secondary" loading={dismiss.isPending} onClick={() => dismiss.mutate(s)}>Keep them separate</Button>
                </div>
              )}
            </li>
          )
        })}
      </ul>

      <Modal open={!!asking} title="Combine these two requests?" onClose={() => { setAsking(undefined); combine.reset() }}>
        {asking && (
          <div className="flex flex-col gap-4">
            <p className="text-sm text-muted">
              {asking.fold_number} is folded into {asking.keep_number}. The quantities are added together, every supplier is asked again for the new total, and
              any quote or approval so far on either request is set aside. {asking.fold_number} is then closed as combined.
            </p>
            {combine.error && <p className="text-sm text-danger">{combine.error.message}</p>}
            <div className="flex justify-end gap-3">
              <Button variant="secondary" onClick={() => { setAsking(undefined); combine.reset() }}>Cancel</Button>
              <Button loading={combine.isPending} onClick={() => combine.mutate(asking, { onSuccess: () => setAsking(undefined) })}>Combine</Button>
            </div>
          </div>
        )}
      </Modal>
    </Card>
  )
}
