import { useState, type FormEvent } from 'react'
import { Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { useConfirm } from '@/components/ui/confirm-context'
import { Input } from '@/components/ui/Field'
import { Modal } from '@/components/ui/Modal'
import { useVendors } from '@/features/vendors/hooks'
import { useRemoveStockItem, useUpdateStockItem } from '../hooks'
import type { StockItem } from '../types'

/** Change an item's name, unit, category and preferred supplier, or remove it. The count and the low-stock levels are changed elsewhere. */
export function EditItemModal({ item, onClose }: { item: StockItem | null; onClose: () => void }) {
  return (
    <Modal open={!!item} title="Edit stock item" onClose={onClose}>
      {item && <EditForm key={item.item_description} item={item} onClose={onClose} />}
    </Modal>
  )
}

function EditForm({ item, onClose }: { item: StockItem; onClose: () => void }) {
  const update = useUpdateStockItem()
  const remove = useRemoveStockItem()
  const confirm = useConfirm()
  const vendors = useVendors()
  const [name, setName] = useState(item.item_description)
  const [unit, setUnit] = useState(item.unit ?? '')
  const [category, setCategory] = useState(item.category ?? '')
  const [supplier, setSupplier] = useState(item.preferred_vendor_id ?? '')
  const busy = update.isPending || remove.isPending
  const error = update.error ?? remove.error

  async function submit(event: FormEvent) {
    event.preventDefault()
    const renamed = name.trim() !== item.item_description
    const ok = await confirm({
      title: 'Save these changes?',
      message: renamed ? (
        <>
          <b>{item.item_description}</b> will be renamed to <b>{name.trim()}</b>. Its history and count stay with it.
        </>
      ) : (
        <>
          The details of <b>{item.item_description}</b> will be updated.
        </>
      ),
      confirmLabel: 'Save changes',
    })
    if (!ok) return
    update.mutate(
      { item_description: item.item_description, new_description: name.trim(), unit: unit.trim() || null, category: category.trim() || null, preferred_vendor_id: supplier || null },
      { onSuccess: onClose },
    )
  }

  async function onRemove() {
    const ok = await confirm({
      title: 'Remove this item?',
      message: (
        <>
          <b>{item.item_description}</b> ({item.quantity_available} in stock) will be removed from the stock list. Its history is kept. This is refused while an open
          order or request refers to it.
        </>
      ),
      confirmLabel: 'Remove item',
      tone: 'danger',
    })
    if (ok) remove.mutate(item.item_description, { onSuccess: onClose })
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <Input label="Item name" required value={name} onChange={(e) => setName(e.target.value)} maxLength={255} />
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Input label="Unit (pcs, kg, box…)" value={unit} onChange={(e) => setUnit(e.target.value)} maxLength={30} placeholder="e.g. pcs" />
        <Input label="Category" value={category} onChange={(e) => setCategory(e.target.value)} maxLength={60} placeholder="e.g. Lighting" />
      </div>
      <label className="flex flex-col gap-1.5 text-xs font-medium text-muted">
        Preferred supplier
        <select
          value={supplier}
          onChange={(e) => setSupplier(e.target.value)}
          className="h-11 rounded-xl border border-line bg-white px-3 text-sm text-title focus:border-brand focus:outline-none focus:ring-4 focus:ring-brand/15"
        >
          <option value="">None</option>
          {(vendors.data ?? []).map((v) => (
            <option key={v.vendor_id} value={v.vendor_id}>
              {v.name}
              {v.email ? '' : ' (no e-mail address)'}
            </option>
          ))}
        </select>
        <span className="font-normal">Always asked for a quote when a request includes this item, and asked first. Everyone else is still asked as usual.</span>
      </label>
      {error && <p className="text-sm text-danger">{error.message}</p>}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button type="button" variant="secondary" onClick={onRemove} disabled={busy} className="text-danger" aria-label={`Remove ${item.item_description}`}>
          <Trash2 size={15} /> Remove
        </Button>
        <div className="flex gap-3">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={update.isPending} disabled={remove.isPending || name.trim() === ''}>
            Save changes
          </Button>
        </div>
      </div>
    </form>
  )
}
