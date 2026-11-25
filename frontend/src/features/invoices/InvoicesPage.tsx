import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search } from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import { Card } from '@/components/ui/Card'
import { DEFAULT_PAGE_SIZE, Pagination } from '@/components/ui/Pagination'
import { QueryState } from '@/components/ui/QueryState'
import { Table, Td, Tr } from '@/components/ui/Table'
import { DownloadExportButton } from '@/features/exports/DownloadExportButton'
import { formatAmount, formatDateTime } from '@/lib/format'
import { useInvoices } from './hooks'

/** Every invoice, newest first (staff). The ones that need a person are a filter away. Click a row for the case. */
export function InvoicesPage() {
  const { data, isLoading, error } = useInvoices()
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('all')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return (data ?? []).filter(
      (i) => (status === 'all' || i.status === status) && (!q || [i.invoice_number ?? '', i.po_number, i.case_number ?? '', i.vendor_name].some((v) => v.toLowerCase().includes(q))),
    )
  }, [data, search, status])
  const rows = filtered.slice((page - 1) * pageSize, page * pageSize)

  return (
    <div className="flex w-full flex-col xl:h-full">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 pb-4">
        <h1 className="page-title">Invoices</h1>
        <div className="flex flex-wrap items-start gap-2">
          <DownloadExportButton kind="invoices" label="CSV" />
          <DownloadExportButton kind="invoices" format="xlsx" label="Excel" />
        </div>
      </div>
      <Card className="flex-1" bodyClassName="flex min-h-0 flex-col p-0">
        <div className="flex shrink-0 flex-wrap items-center gap-3 border-b border-line px-5 py-3">
          <div className="relative min-w-[220px] flex-1 sm:max-w-xs">
            <Search size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" />
            <input
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(1) }}
              placeholder="Search invoice, order, case or supplier"
              aria-label="Search invoices"
              className="h-10 w-full rounded-xl border border-line pl-10 pr-3 text-sm focus:border-brand focus:outline-none focus:ring-4 focus:ring-brand/15"
            />
          </div>
          <select
            value={status}
            onChange={(e) => { setStatus(e.target.value); setPage(1) }}
            aria-label="Filter by status"
            className="h-10 rounded-xl border border-line bg-white px-3 text-sm focus:border-brand focus:outline-none"
          >
            <option value="all">All invoices</option>
            <option value="mismatch">Needs a person</option>
            <option value="on_hold">On hold</option>
            <option value="matched">Matched</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
          </select>
        </div>
        <QueryState variant="table" columns={8} isLoading={isLoading} error={error} isEmpty={!filtered.length} emptyMessage="No invoices found.">
          <Table headers={['Sr.No.', 'Invoice', 'Order', 'Case', 'Supplier', 'Total', 'Status', 'Received']}>
            {rows.map((i, k) => (
              <Tr key={i.invoice_id} onClick={() => navigate(`/cases/${i.case_id}`)}>
                <Td first>{String((page - 1) * pageSize + k + 1).padStart(2, '0')}.</Td>
                <Td className="whitespace-nowrap font-medium">{i.invoice_number ?? 'Unreadable number'}</Td>
                <Td className="whitespace-nowrap tabular-nums">{i.po_number}</Td>
                <Td className="whitespace-nowrap tabular-nums">{i.case_number ?? i.case_id.slice(0, 8)}</Td>
                <Td>{i.vendor_name}</Td>
                <Td className="whitespace-nowrap tabular-nums">
                  {formatAmount(i.total_amount)}
                  {i.tax_amount !== null && i.tax_amount !== undefined && <span className="block text-xs text-muted">tax {formatAmount(i.tax_amount)}</span>}
                </Td>
                <Td>
                  <Badge value={i.status} />
                  {i.issues.length > 0 && i.status === 'mismatch' && <span className="mt-0.5 block max-w-[260px] truncate text-xs text-muted" title={i.issues.join(' ')}>{i.issues[0]}</span>}
                </Td>
                <Td>{formatDateTime(i.created_at)}</Td>
              </Tr>
            ))}
          </Table>
        </QueryState>
        <Pagination page={page} pageSize={pageSize} totalItems={filtered.length} onPageChange={setPage} onPageSizeChange={(n) => { setPageSize(n); setPage(1) }} itemLabel="invoices" />
      </Card>
    </div>
  )
}
