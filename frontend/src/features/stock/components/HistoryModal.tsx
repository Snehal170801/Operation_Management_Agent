import { Link } from 'react-router-dom'
import clsx from 'clsx'
import { Bot, User } from 'lucide-react'
import { Modal } from '@/components/ui/Modal'
import { QueryState } from '@/components/ui/QueryState'
import { formatDateTime } from '@/lib/format'
import { useStockHistory } from '../hooks'
import type { StockHistoryEntry, StockItem } from '../types'

/** "+12" in green, "-5" in red, so a glance shows whether stock went up or down. */
function Change({ value }: { value: number }) {
  const up = value > 0
  return (
    <span
      className={clsx(
        'inline-flex min-w-[3.25rem] justify-center rounded-full px-2.5 py-0.5 text-sm font-semibold tabular-nums',
        value === 0 ? 'bg-slate-100 text-slate-600' : up ? 'bg-[#DCFCE7] text-[#16A34A]' : 'bg-danger-soft text-danger',
      )}
    >
      {value > 0 ? `+${value}` : value < 0 ? `−${Math.abs(value)}` : '0'}
    </span>
  )
}

function Entry({ e }: { e: StockHistoryEntry }) {
  const Who = e.by_a_person ? User : Bot
  return (
    <li className="flex flex-col gap-1.5 py-3.5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <Change value={e.change} />
        <span className="text-sm font-semibold tabular-nums text-title">
          {e.old_quantity} → {e.new_quantity}
        </span>
        <span className="text-sm font-medium text-title">{e.reason_label}</span>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
        <span>{formatDateTime(e.created_at)}</span>
        <span className="inline-flex items-center gap-1">
          <Who size={12} aria-hidden /> {e.actor}
        </span>
        {e.case_id && (
          <Link to={`/cases/${e.case_id}`} className="font-semibold text-brand-ink hover:underline">
            {e.case_number ?? 'Open the case'}
          </Link>
        )}
      </div>
      {e.note && <p className="text-xs text-muted">{e.note}</p>}
    </li>
  )
}

/** Every change to one item's stock count: who, when, old and new value, why, and the case. Newest first. */
export function HistoryModal({ item, onClose }: { item: StockItem | null; onClose: () => void }) {
  const history = useStockHistory(item?.item_description ?? null)
  const entries = history.data ?? []
  return (
    <Modal open={!!item} title="Stock history" onClose={onClose} size="lg">
      {item && (
        <div className="flex flex-col gap-3">
          <p className="text-sm text-muted">
            <b className="text-title">{item.item_description}</b>: {item.quantity_available} in stock now.
          </p>
          <QueryState variant="lines" rows={4} isLoading={history.isLoading} error={history.error} isEmpty={!entries.length} emptyMessage="No changes have been recorded for this item yet.">
            <ul className="divide-y divide-line" aria-label="Changes to this item's stock count">
              {entries.map((e) => (
                <Entry key={e.entry_id} e={e} />
              ))}
            </ul>
          </QueryState>
        </div>
      )}
    </Modal>
  )
}
