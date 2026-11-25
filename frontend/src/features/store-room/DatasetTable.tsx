import { Link } from 'react-router-dom'
import { Star } from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import { Table, Td, Tr } from '@/components/ui/Table'
import { formatAmount, formatDate, formatDateTime } from '@/lib/format'
import type { StoreColumn, StoreRow } from './types'

function Cell({ column, value }: { column: StoreColumn; value: StoreRow[string] }) {
  const empty = value === null || value === undefined || value === ''
  if (empty && column.kind !== 'list') return <span className="text-muted">—</span>

  switch (column.kind) {
    case 'badge':
      return <Badge value={String(value)} />
    case 'note':
      return <span className="rounded-full bg-brand-tint px-2.5 py-0.5 text-xs font-medium text-brand-ink">{String(value)}</span>
    case 'money':
      return <span className="tabular-nums">{formatAmount(Number(value))}</span>
    case 'int':
      return <span className="tabular-nums">{Number(value).toLocaleString()}</span>
    case 'rating':
      return (
        <span className="inline-flex items-center gap-1 font-semibold text-brand-ink">
          <Star size={13} fill="currentColor" /> {Number(value).toFixed(1)}
        </span>
      )
    case 'date':
      return <>{formatDate(String(value))}</>
    case 'datetime':
      return <>{formatDateTime(String(value))}</>
    case 'case': {
      const ref = typeof value === 'object' && value !== null && !Array.isArray(value) ? value : { id: String(value), number: null }
      const id = ref.id
      return (
        <Link to={`/cases/${id}`} className="tabular-nums text-xs font-medium text-brand-ink hover:underline" title={id}>
          {ref.number ?? id.slice(0, 8).toLowerCase()}
        </Link>
      )
    }
    case 'list': {
      const items = Array.isArray(value) ? value : []
      return items.length ? (
        <ul className="list-disc py-1 pl-4 text-xs">
          {items.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : (
        <span className="text-muted">—</span>
      )
    }
    case 'longtext':
      return (
        <span className="block max-w-[320px] truncate" title={String(value)}>
          {String(value)}
        </span>
      )
    default:
      return <>{String(value)}</>
  }
}

/** A dataset as a table, in the same style as the other pages (numbered rows). The server says which
 *  columns there are and how each is drawn. `offset` keeps the numbering going across pages. */
export function DatasetTable({ columns, rows, offset = 0 }: { columns: StoreColumn[]; rows: StoreRow[]; offset?: number }) {
  return (
    <Table headers={['Sr.No.', ...columns.map((c) => c.label)]}>
      {rows.map((row, i) => (
        <Tr key={i}>
          <Td first>{String(offset + i + 1).padStart(2, '0')}.</Td>
          {columns.map((column) => (
            <Td key={column.key} className="whitespace-nowrap">
              <Cell column={column} value={row[column.key]} />
            </Td>
          ))}
        </Tr>
      ))}
    </Table>
  )
}
