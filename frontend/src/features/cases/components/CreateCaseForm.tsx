import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/Button'
import { useConfirm } from '@/components/ui/confirm-context'
import { Input, Textarea } from '@/components/ui/Field'
import { Modal } from '@/components/ui/Modal'
import { useCreateCase } from '../hooks'
import { UrgencyFields } from './UrgencyFields'

export function CreateCaseModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [requesterId, setRequesterId] = useState('')
  const [rawRequest, setRawRequest] = useState('')
  const [neededBy, setNeededBy] = useState('')
  const [urgent, setUrgent] = useState(false)
  const navigate = useNavigate()
  const createCase = useCreateCase()
  const confirm = useConfirm()

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    const onBehalf = requesterId.trim()
    const ok = await confirm({
      title: 'Create this case?',
      message: `A new case will be opened${onBehalf ? ` for ${onBehalf}` : ''} and the agents will start working on it straight away.`,
      confirmLabel: 'Create case',
    })
    if (!ok) return
    createCase.mutate(
      { requester_id: requesterId.trim() || undefined, raw_request: rawRequest, needed_by: neededBy || undefined, urgent },
      {
        onSuccess: ({ case_id }) => {
          setRequesterId('')
          setRawRequest('')
          setNeededBy('')
          setUrgent(false)
          onClose()
          navigate(`/cases/${case_id}`)
        },
      },
    )
  }

  return (
    <Modal open={open} title="New case" onClose={onClose}>
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <Input label="Requester (optional - leave blank to file as yourself)" value={requesterId} onChange={(e) => setRequesterId(e.target.value)} />
        <Textarea
          label="Request"
          required
          rows={4}
          value={rawRequest}
          onChange={(e) => setRawRequest(e.target.value)}
          placeholder="e.g. 10 laptops for the sales team"
        />
        <UrgencyFields neededBy={neededBy} urgent={urgent} onNeededBy={setNeededBy} onUrgent={setUrgent} />
        {createCase.error && <p className="text-sm text-danger">{createCase.error.message}</p>}
        <div className="flex justify-end gap-3">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={createCase.isPending}>Create case</Button>
        </div>
      </form>
    </Modal>
  )
}
