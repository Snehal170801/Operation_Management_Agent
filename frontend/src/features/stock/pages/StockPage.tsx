import { useMemo, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { History, Plus, Pencil, Settings2, ShoppingCart } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { useConfirm } from '@/components/ui/confirm-context'
import { useAuth } from '@/features/auth/AuthContext'
import { Card } from '@/components/ui/Card'
import { Input } from '@/components/ui/Field'
import { Modal } from '@/components/ui/Modal'
import { DEFAULT_PAGE_SIZE, Pagination } from '@/components/ui/Pagination'
import { QueryState } from '@/components/ui/QueryState'
import { Table, Td, Tr } from '@/components/ui/Table'
import { formatDateTime } from '@/lib/format'
import { DownloadExportButton } from '@/features/exports/DownloadExportButton'
import { EditItemModal } from '../components/EditItemModal'
import { HistoryModal } from '../components/HistoryModal'
import { LevelsModal } from '../components/LevelsModal'
import { ReorderModal } from '../components/ReorderModal'
import { useStock, useUpsertStock } from '../hooks'
import type { StockItem } from '../types'

export function StockPage() {
  const { can } = useAuth()
  const { data, isLoading, error } = useStock()
  const upsert = useUpsertStock()
  const confirm = useConfirm()
  const [open, setOpen] = useState(false)
  const [description, setDescription] = useState('')
  const [quantity, setQuantity] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)
  const [ordering, setOrdering] = useState<StockItem | null>(null)
  const [levelling, setLevelling] = useState<StockItem | null>(null)
  const [viewing, setViewing] = useState<StockItem | null>(null)
  const [editing, setEditing] = useState<StockItem | null>(null)
  // Whoever may change stock (Stores, the administrator) sets the levels and can order what is low.
  const canManage = can('stock:write')

  const items = useMemo(() => data ?? [], [data])
  const rows = items.slice((page - 1) * pageSize, page * pageSize)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    const existing = items.some((i) => i.item_description.toLowerCase() === description.trim().toLowerCase())
    const ok = await confirm({
      title: existing ? 'Update this stock level?' : 'Add this stock item?',
      message: existing
        ? `"${description.trim()}" will be set to ${quantity} available, replacing the current number.`
        : `"${description.trim()}" will be added with ${quantity} available.`,
      confirmLabel: existing ? 'Update stock' : 'Add item',
    })
    if (!ok) return
    upsert.mutate(
      { item_description: description, quantity_available: quantity },
      {
        onSuccess: () => {
          setDescription('')
          setQuantity(0)
          setOpen(false)
        },
      },
    )
  }

  return (
    <div className="flex w-full flex-col xl:h-full">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 pb-4">
        <h1 className="page-title">Stock</h1>
        <div className="flex flex-wrap items-start gap-2">
          <DownloadExportButton kind="stock" label="CSV" />
          <DownloadExportButton kind="stock" format="xlsx" label="Excel" />
          {can('stock:write') && (
            <Button onClick={() => setOpen(true)}>
              <Plus size={18} /> Add / update item
            </Button>
          )}
        </div>
      </div>

      <Card className="flex-1" bodyClassName="flex min-h-0 flex-col p-0">
        <QueryState variant="table" columns={7} isLoading={isLoading} error={error} isEmpty={!items.length} emptyMessage="No stock recorded.">
          <Table headers={['Sr.No.', 'Item', 'Available', 'Levels', 'Status', 'Updated', 'Action']}>
            {rows.map((s, i) => (
              <Tr key={s.item_description}>
                <Td first>{String((page - 1) * pageSize + i + 1).padStart(2, '0')}.</Td>
                <Td>
                  {s.item_description}
                  {(s.category || s.preferred_vendor_name) && (
                    <span className="mt-0.5 block text-xs text-muted">
                      {[s.category, s.preferred_vendor_name && `Preferred: ${s.preferred_vendor_name}`].filter(Boolean).join(' · ')}
                    </span>
                  )}
                </Td>
                <Td className="font-semibold">
                  {s.quantity_available}
                  {s.unit && <span className="ml-1 text-xs font-normal text-muted">{s.unit}</span>}
                </Td>
                <Td className="text-muted">{s.min_level != null ? `min ${s.min_level} · target ${s.target_level}` : 'Not set'}</Td>
                <Td>
                  {s.low ? (
                    <span className="inline-flex rounded-full bg-danger-soft px-2.5 py-0.5 text-xs font-semibold text-danger">Low</span>
                  ) : s.min_level != null ? (
                    <span className="inline-flex rounded-full bg-[#DCFCE7] px-2.5 py-0.5 text-xs font-semibold text-[#16A34A]">OK</span>
                  ) : (
                    <span className="text-muted">–</span>
                  )}
                </Td>
                <Td>{formatDateTime(s.updated_at)}</Td>
                <Td>
                  <div className="flex flex-wrap items-center gap-2">
                    {s.open_order ? (
                      <Link to={`/cases/${s.open_order.case_id}`} className="text-sm font-semibold text-brand-ink hover:underline">
                        Ordered{s.open_order.case_number ? ` · ${s.open_order.case_number}` : ''}
                      </Link>
                    ) : (
                      s.low && canManage && (
                        <Button onClick={() => setOrdering(s)}>
                          <ShoppingCart size={15} /> Order now
                        </Button>
                      )
                    )}
                    <Button variant="secondary" onClick={() => setViewing(s)} aria-label={`Show the history of ${s.item_description}`}>
                      <History size={15} /> History
                    </Button>
                    {canManage && (
                      <Button variant="secondary" onClick={() => setEditing(s)} aria-label={`Edit ${s.item_description}`}>
                        <Settings2 size={15} /> Edit
                      </Button>
                    )}
                    {canManage && (
                      <Button variant="secondary" onClick={() => setLevelling(s)} aria-label={`Set levels for ${s.item_description}`}>
                        <Pencil size={15} /> Levels
                      </Button>
                    )}
                  </div>
                </Td>
              </Tr>
            ))}
          </Table>
        </QueryState>
        <Pagination
          page={page}
          pageSize={pageSize}
          totalItems={items.length}
          onPageChange={setPage}
          onPageSizeChange={(n) => { setPageSize(n); setPage(1) }}
          itemLabel="items"
        />
      </Card>

      <ReorderModal item={ordering} onClose={() => setOrdering(null)} />
      <LevelsModal item={levelling} onClose={() => setLevelling(null)} />
      <HistoryModal item={viewing} onClose={() => setViewing(null)} />
      <EditItemModal item={editing} onClose={() => setEditing(null)} />

      <Modal open={open} title="Add or update stock item" onClose={() => setOpen(false)}>
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <Input label="Item description" required value={description} onChange={(e) => setDescription(e.target.value)} />
          <Input
            label="Quantity available"
            type="number"
            min={0}
            required
            value={quantity}
            onChange={(e) => setQuantity(Number(e.target.value))}
          />
          {upsert.error && <p className="text-sm text-danger">{upsert.error.message}</p>}
          <div className="flex justify-end gap-3">
            <Button type="button" variant="secondary" onClick={() => setOpen(false)}>Cancel</Button>
            <Button type="submit" loading={upsert.isPending}>Save</Button>
          </div>
        </form>
      </Modal>
    </div>
  )
}
