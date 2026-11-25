import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { Send } from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { useConfirm } from '@/components/ui/confirm-context'
import { Card } from '@/components/ui/Card'
import { Textarea } from '@/components/ui/Field'
import { QueryState } from '@/components/ui/QueryState'
import { Table, Td, Tr } from '@/components/ui/Table'
import { describeCase } from '@/lib/caseFlow'
import { formatDateTime } from '@/lib/format'
import { useCases, useCreateCase } from '@/features/cases/hooks'
import { UrgencyFields } from '@/features/cases/components/UrgencyFields'
import { UrgentBadge } from '@/features/cases/components/UrgentBadge'

const MAX_LENGTH = 2000

/** The requester's whole app: write what you need, send it, and follow the agents. */
export function MyRequestsPage() {
  const navigate = useNavigate()
  const { data, isLoading, error } = useCases()
  const createCase = useCreateCase()
  const confirm = useConfirm()
  const [text, setText] = useState('')
  const [neededBy, setNeededBy] = useState('')
  const [urgent, setUrgent] = useState(false)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    const ok = await confirm({
      title: 'Send this request?',
      message: 'The agents will start working on it straight away. You can follow its progress here.',
      confirmLabel: 'Send request',
    })
    if (!ok) return
    createCase.mutate(
      { raw_request: text.trim(), needed_by: neededBy || undefined, urgent },
      {
        onSuccess: ({ case_id }) => {
          setText('')
          setNeededBy('')
          setUrgent(false)
          navigate(`/requests/${case_id}`)
        },
      },
    )
  }

  return (
    <div className="flex w-full max-w-5xl flex-col gap-4">
      <h1 className="page-title">My requests</h1>

      <Card title="What do you need?">
        <form onSubmit={onSubmit} className="flex flex-col gap-3">
          <Textarea
            label="Describe your request in your own words"
            required
            rows={4}
            maxLength={MAX_LENGTH}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="e.g. I need 10 laptops for the sales team, and 2 monitors"
          />
          <UrgencyFields neededBy={neededBy} urgent={urgent} onNeededBy={setNeededBy} onUrgent={setUrgent} />
          {createCase.error && <p className="text-sm text-danger">{createCase.error.message}</p>}
          <div className="flex items-center justify-between gap-3">
            <span className="text-xs text-muted">
              {text.length}/{MAX_LENGTH}
            </span>
            <Button type="submit" loading={createCase.isPending} disabled={!text.trim()}>
              <Send size={16} /> Submit request
            </Button>
          </div>
        </form>
      </Card>

      <Card title="Your requests" bodyClassName="flex min-h-0 flex-col p-0">
        <QueryState
          variant="table" columns={4}
          isLoading={isLoading}
          error={error}
          isEmpty={!data?.length}
          emptyMessage="You haven't submitted any requests yet."
        >
          <Table headers={['No.', 'Request', 'Where it is', 'Status', 'Updated']}>
            {data?.map((c) => (
              <Tr key={c.case_id} onClick={() => navigate(`/requests/${c.case_id}`)}>
                <Td first className="whitespace-nowrap font-medium tabular-nums">{c.case_number ?? '—'}</Td>
                <Td className="max-w-[260px] truncate">
                  {c.urgent && <UrgentBadge neededBy={c.needed_by} />} {c.items_summary ?? 'Reading your request…'}
                </Td>
                <Td className="max-w-[320px] truncate">{describeCase(c.stage, c.status).headline}</Td>
                <Td>
                  <Badge value={c.status} />
                </Td>
                <Td>{formatDateTime(c.updated_at)}</Td>
              </Tr>
            ))}
          </Table>
        </QueryState>
      </Card>
    </div>
  )
}
