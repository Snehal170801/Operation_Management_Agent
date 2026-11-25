import { useState } from 'react'
import { Pause, Play } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { Modal } from '@/components/ui/Modal'
import { QueryState } from '@/components/ui/QueryState'
import { useAuth } from '@/features/auth/AuthContext'
import { formatDateTime } from '@/lib/format'
import { useAutomation, useSetAutomation } from '../automation'

const WHAT_STOPS = [
  'Quote requests to suppliers, and reminders to suppliers who have not replied',
  'Reading supplier replies and invoices from the mailbox',
  'Raising purchase orders and emailing them to suppliers',
  'Chasing suppliers about late deliveries and approval reminders',
]

/** The pause switch for everything the agents do on their own. */
export function AutomationSection() {
  const { can } = useAuth()
  const { data, isLoading, error } = useAutomation()
  const set = useSetAutomation()
  const [confirming, setConfirming] = useState(false)

  const paused = data?.paused ?? false

  return (
    <Card title="Automation">
      <QueryState variant="detail" rows={2} isLoading={isLoading} error={error} isEmpty={!data}>
        <div className="flex flex-col gap-4 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <span
                className={
                  'inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ' +
                  (paused ? 'bg-amber-100 text-amber-700' : 'bg-[#DCFCE7] text-[#16A34A]')
                }
              >
                {paused ? 'Paused' : 'Running'}
              </span>
              {data?.updated_by && (
                <p className="mt-1 text-xs text-muted">
                  Last changed by {data.updated_by} · {formatDateTime(data.updated_at)}
                </p>
              )}
            </div>
            {can('system:write') && (
              <Button
                variant={paused ? 'primary' : 'secondary'}
                loading={set.isPending}
                onClick={() => (paused ? set.mutate(false) : setConfirming(true))}
              >
                {paused ? <Play size={16} /> : <Pause size={16} />} {paused ? 'Resume automation' : 'Pause automation'}
              </Button>
            )}
          </div>

          <p className="text-muted">
            {paused
              ? 'The agents are idle. People can still use the app, and new requests are accepted but held. Anything held is caught up automatically after you resume.'
              : 'The agents are working on their own. Use the pause switch if something looks wrong; it takes effect within a minute.'}
          </p>

          <div>
            <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">Pausing stops</h3>
            <ul className="list-disc pl-5 text-title">
              {WHAT_STOPS.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </div>
          {set.error && <p className="text-danger">{set.error.message}</p>}
        </div>
      </QueryState>

      <Modal open={confirming} title="Pause all automation?" onClose={() => setConfirming(false)}>
        <div className="flex flex-col gap-4">
          <p className="text-sm text-muted">
            No quote requests, orders or vendor emails will be sent, and the mailbox will not be read, until you resume.
            Requests can still be submitted; they will be held and picked up after you resume.
          </p>
          <div className="flex justify-end gap-3">
            <Button type="button" variant="secondary" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
            <Button
              type="button"
              loading={set.isPending}
              onClick={() => set.mutate(true, { onSuccess: () => setConfirming(false) })}
            >
              Pause automation
            </Button>
          </div>
        </div>
      </Modal>
    </Card>
  )
}
