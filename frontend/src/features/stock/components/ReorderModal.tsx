import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Field'
import { Modal } from '@/components/ui/Modal'
import { UrgencyFields } from '@/features/cases/components/UrgencyFields'
import { useReorder } from '../hooks'
import type { StockItem } from '../types'

/** Order more of an item that is running low. It becomes an ordinary request: quotes, a choice of supplier, approval, delivery, invoice. */
export function ReorderModal({ item, onClose }: { item: StockItem | null; onClose: () => void }) {
  return (
    <Modal open={!!item} title="Order more" onClose={onClose}>
      {item && <ReorderForm key={item.item_description} item={item} onClose={onClose} />}
    </Modal>
  )
}

function ReorderForm({ item, onClose }: { item: StockItem; onClose: () => void }) {
  const navigate = useNavigate()
  const reorder = useReorder()
  const [quantity, setQuantity] = useState(item.suggested_quantity ?? 1)
  const [neededBy, setNeededBy] = useState('')
  const [urgent, setUrgent] = useState(false)

  function submit(event: FormEvent) {
    event.preventDefault()
    reorder.mutate(
      { item_description: item.item_description, quantity, needed_by: neededBy || undefined, urgent },
      { onSuccess: (r) => { onClose(); navigate(`/cases/${r.case_id}`) } },
    )
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <p className="text-sm text-muted">
        <b className="text-title">{item.item_description}</b>: {item.quantity_available} in stock
        {item.min_level != null && <>, minimum {item.min_level}</>}
        {item.target_level != null && <>, target {item.target_level}</>}.
      </p>
      <Input label="How many to order" type="number" min={1} required value={quantity} onChange={(e) => setQuantity(Number(e.target.value))} />
      {item.suggested_quantity != null && (
        <p className="-mt-2 text-xs text-muted">Suggested: {item.suggested_quantity}, enough to reach the target of {item.target_level}.</p>
      )}
      <UrgencyFields neededBy={neededBy} urgent={urgent} onNeededBy={setNeededBy} onUrgent={setUrgent} />
      <p className="text-xs text-muted">
        This starts a normal request. Suppliers are asked for prices and the best offer is picked. An approver must then approve it before anything is ordered.
      </p>
      {reorder.error && <p className="text-sm text-danger">{reorder.error.message}</p>}
      <div className="flex justify-end gap-3">
        <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
        <Button type="submit" loading={reorder.isPending} disabled={!Number.isInteger(quantity) || quantity < 1}>Place order</Button>
      </div>
    </form>
  )
}
