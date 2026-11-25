import { useState, type FormEvent } from 'react'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Field'
import { Modal } from '@/components/ui/Modal'
import { useSetLevels } from '../hooks'
import type { StockItem } from '../types'

/** The administrator says when an item counts as low, and how many to bring it back up to. Both empty switches it off. */
export function LevelsModal({ item, onClose }: { item: StockItem | null; onClose: () => void }) {
  return (
    <Modal open={!!item} title="Low-stock levels" onClose={onClose}>
      {item && <LevelsForm key={item.item_description} item={item} onClose={onClose} />}
    </Modal>
  )
}

function LevelsForm({ item, onClose }: { item: StockItem; onClose: () => void }) {
  const save = useSetLevels()
  const [min, setMin] = useState(item.min_level?.toString() ?? '')
  const [target, setTarget] = useState(item.target_level?.toString() ?? '')
  const num = (v: string) => (v.trim() === '' ? null : Number(v))
  const bothEmpty = min.trim() === '' && target.trim() === ''
  const half = !bothEmpty && (min.trim() === '' || target.trim() === '')
  const backwards = !half && !bothEmpty && Number(target) < Number(min)

  function submit(event: FormEvent) {
    event.preventDefault()
    save.mutate({ item_description: item.item_description, min_level: num(min), target_level: num(target) }, { onSuccess: onClose })
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <p className="text-sm text-muted">
        <b className="text-title">{item.item_description}</b>: {item.quantity_available} in stock.
      </p>
      <div className="grid grid-cols-2 gap-3">
        <Input label="Minimum level" type="number" min={0} value={min} onChange={(e) => setMin(e.target.value)} placeholder="e.g. 10" />
        <Input label="Target level" type="number" min={0} value={target} onChange={(e) => setTarget(e.target.value)} placeholder="e.g. 30" />
      </div>
      <p className="text-xs text-muted">
        The item is marked <b>Low</b> when its stock falls to the minimum or below. “Order now” then suggests enough to reach the target. Leave both empty to
        stop tracking it.
      </p>
      {half && <p className="text-sm text-danger">Fill in both numbers, or leave both empty.</p>}
      {backwards && <p className="text-sm text-danger">The target cannot be lower than the minimum.</p>}
      {save.error && <p className="text-sm text-danger">{save.error.message}</p>}
      <div className="flex justify-end gap-3">
        <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
        <Button type="submit" loading={save.isPending} disabled={half || backwards}>Save</Button>
      </div>
    </form>
  )
}
