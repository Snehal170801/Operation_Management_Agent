import { ChevronLeft, ChevronRight } from 'lucide-react'
import clsx from 'clsx'

export const PAGE_SIZE_OPTIONS = [10, 20, 30, 40, 50]
export const DEFAULT_PAGE_SIZE = 10

interface PaginationProps {
  page: number
  pageSize: number
  totalItems: number
  onPageChange: (page: number) => void
  onPageSizeChange: (size: number) => void
  itemLabel?: string
}

export function Pagination({ page, pageSize, totalItems, onPageChange, onPageSizeChange, itemLabel = 'items' }: PaginationProps) {
  if (totalItems === 0) return null
  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize))
  const start = (page - 1) * pageSize + 1
  const end = Math.min(page * pageSize, totalItems)

  const nav = 'flex h-10 w-10 md:h-8 md:w-8 items-center justify-center rounded-lg border border-line text-muted hover:bg-brand-tint disabled:opacity-40'

  return (
    <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-3">
      <div className="flex flex-wrap items-center gap-3 text-xs text-muted">
        <span>
          Showing <b className="text-title">{start}–{end}</b> of <b className="text-title">{totalItems}</b> {itemLabel}
        </span>
        <label className="flex items-center gap-1.5">
          Rows per page
          <select
            value={pageSize}
            onChange={(e) => onPageSizeChange(Number(e.target.value))}
            className="rounded-lg border border-line bg-white px-2 py-1 text-xs font-medium focus:outline-none focus:ring-2 focus:ring-brand/20"
          >
            {PAGE_SIZE_OPTIONS.map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </label>
      </div>
      <div className="flex items-center gap-1.5">
        <button type="button" className={nav} disabled={page <= 1} onClick={() => onPageChange(page - 1)} aria-label="Previous page">
          <ChevronLeft size={16} />
        </button>
        <span className={clsx('px-2 text-xs font-medium text-title')}>
          {page} / {totalPages}
        </span>
        <button type="button" className={nav} disabled={page >= totalPages} onClick={() => onPageChange(page + 1)} aria-label="Next page">
          <ChevronRight size={16} />
        </button>
      </div>
    </div>
  )
}
