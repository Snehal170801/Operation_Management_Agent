import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search } from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import { Card } from '@/components/ui/Card'
import { DEFAULT_PAGE_SIZE, Pagination } from '@/components/ui/Pagination'
import { QueryState } from '@/components/ui/QueryState'
import { Table, Td, Tr } from '@/components/ui/Table'
import { DownloadExportButton } from '@/features/exports/DownloadExportButton'
import { formatAmount, formatDate, formatDateTime } from '@/lib/format'
import { usePurchaseOrders } from './hooks'

/** Every purchase order, newest first (staff). Click a row for the case. */
export function PurchaseOrdersPage() {
  const { data, isLoading, error } = usePurchaseOrders()
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('all')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return (data ?? []).filter(
      (p) => (status === 'all' || p.status === status || p.delivery_status === status) && (!q || [p.po_number, p.case_number ?? '', p.vendor_name].some((v) => v.toLowerCase().includes(q))),
    )
  }, [data, search, status])
  const rows = filtered.slice((page - 1) * pageSize, page * pageSize)

  return (
    <div className="flex w-full flex-col xl:h-full">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 pb-4">
        <h1 className="page-title">Purchase orders</h1>
        <div className="flex flex-wrap items-start gap-2">
          <DownloadExportButton kind="purchase-orders" label="CSV" />
          <DownloadExportButton kind="purchase-orders" format="xlsx" label="Excel" />
        </div>
      </div>
      <Card className="flex-1" bodyClassName="flex min-h-0 flex-col p-0">
        <div className="flex shrink-0 flex-wrap items-center gap-3 border-b border-line px-5 py-3">
          <div className="relative min-w-[220px] flex-1 sm:max-w-xs">
            <Search size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" />
            <input
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(1) }}
              placeholder="Search order, case or supplier"
              aria-label="Search purchase orders"
              className="h-10 w-full rounded-xl border border-line pl-10 pr-3 text-sm focus:border-brand focus:outline-none focus:ring-4 focus:ring-brand/15"
            />
          </div>
          <select
            value={status}
            onChange={(e) => { setStatus(e.target.value); setPage(1) }}
            aria-label="Filter by status"
            className="h-10 rounded-xl border border-line bg-white px-3 text-sm focus:border-brand focus:outline-none"
          >
            <option value="all">All orders</option>
            <option value="sent">Sent</option>
            <option value="send_failed">E-mail failed</option>
            <option value="pending">Waiting for delivery</option>
            <option value="delivered">Delivered</option>
          </select>
        </div>
        <QueryState variant="table" columns={8} isLoading={isLoading} error={error} isEmpty={!filtered.length} emptyMessage="No purchase orders found.">
          <Table headers={['Sr.No.', 'Order', 'Case', 'Supplier', 'Total', 'Status', 'Delivery', 'Created']}>
            {rows.map((p, i) => (
              <Tr key={p.purchase_order_id} onClick={() => navigate(`/cases/${p.case_id}`)}>
                <Td first>{String((page - 1) * pageSize + i + 1).padStart(2, '0')}.</Td>
                <Td className="whitespace-nowrap font-medium tabular-nums">{p.po_number}</Td>
                <Td className="whitespace-nowrap tabular-nums">{p.case_number ?? p.case_id.slice(0, 8)}</Td>
                <Td>{p.vendor_name}</Td>
                <Td className="whitespace-nowrap tabular-nums">
                  {formatAmount(p.total_with_tax ?? p.total_amount)}
                  {p.tax_amount !== null && <span className="block text-xs text-muted">incl. tax {formatAmount(p.tax_amount)}</span>}
                </Td>
                <Td><Badge value={p.status} /></Td>
                <Td>
                  <Badge value={p.delivery_status ?? 'pending'} />
                  {p.expected_delivery_date && p.delivery_status !== 'delivered' && <span className="block text-xs text-muted">due {formatDate(p.expected_delivery_date)}</span>}
                </Td>
                <Td>{formatDateTime(p.created_at)}</Td>
              </Tr>
            ))}
          </Table>
        </QueryState>
        <Pagination page={page} pageSize={pageSize} totalItems={filtered.length} onPageChange={setPage} onPageSizeChange={(n) => { setPageSize(n); setPage(1) }} itemLabel="orders" />
      </Card>
    </div>
  )
}
