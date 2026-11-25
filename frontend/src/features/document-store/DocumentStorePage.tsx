import { useState } from 'react'
import { Link } from 'react-router-dom'
import { FileSearch, FileText, Paperclip, Receipt, Search, Tag } from 'lucide-react'
import clsx from 'clsx'
import { Card } from '@/components/ui/Card'
import { Pagination } from '@/components/ui/Pagination'
import { QueryState } from '@/components/ui/QueryState'
import { Table, Td, Tr } from '@/components/ui/Table'
import { useAuth } from '@/features/auth/AuthContext'
import { useDebounced } from '@/features/store-room/hooks'
import { formatAmount, formatDateTime } from '@/lib/format'
import { useDocumentSearch } from './hooks'
import type { DocumentKind } from './types'

const KIND_ICON: Record<DocumentKind, typeof FileText> = { purchase_order: FileText, invoice: Receipt, quote: Tag, file: Paperclip }
const TABS: { key: DocumentKind | ''; label: string }[] = [
  { key: '', label: 'All' },
  { key: 'purchase_order', label: 'Purchase orders' },
  { key: 'invoice', label: 'Invoices' },
  { key: 'quote', label: 'Quotes' },
  { key: 'file', label: 'Files received' },
]

/** Every purchase order, invoice, quote and file received, in one searchable list. Staff see everything; a requester sees only that
 * their own cases have an order or an invoice (the server decides, this page only shows what it is given). */
export function DocumentStorePage() {
  const { can } = useAuth()
  const staff = can('cases:read_all')
  const [text, setText] = useState('')
  const q = useDebounced(text.trim(), 300)
  const [kind, setKind] = useState<DocumentKind | ''>('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const { data, isLoading, error } = useDocumentSearch(q, kind, pageSize, (page - 1) * pageSize)
  const tabs = staff ? TABS : TABS.filter((t) => t.key === '' || t.key === 'purchase_order' || t.key === 'invoice')
  const caseLink = (id: string) => (staff ? `/cases/${id}` : `/requests/${id}`)

  return (
    <div className="flex w-full flex-col xl:h-full">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 pb-4">
        <h1 className="page-title">Document store</h1>
      </div>
      <Card className="flex-1" bodyClassName="flex min-h-0 flex-col p-0">
        <div className="flex shrink-0 flex-col gap-3 border-b border-line px-5 py-3">
          <div className="relative max-w-xl">
            <Search size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" />
            <input
              value={text}
              onChange={(e) => { setText(e.target.value); setPage(1) }}
              placeholder={staff ? 'Search by case, supplier, order or invoice number, amount, file name' : 'Search by request number'}
              aria-label="Search documents"
              maxLength={100}
              className="h-10 w-full rounded-xl border border-line pl-10 pr-3 text-sm focus:border-brand focus:outline-none focus:ring-4 focus:ring-brand/15"
            />
          </div>
          <div role="tablist" className="flex flex-wrap gap-2">
            {tabs.map((t) => {
              const count = t.key ? data?.counts[t.key] : data ? Object.values(data.counts).reduce((a, b) => a + b, 0) : undefined
              return (
                <button
                  key={t.key || 'all'}
                  type="button"
                  role="tab"
                  aria-selected={kind === t.key}
                  onClick={() => { setKind(t.key); setPage(1) }}
                  className={clsx('inline-flex h-9 items-center gap-2 rounded-xl px-3.5 text-sm font-medium', kind === t.key ? 'bg-brand-soft text-brand-ink' : 'bg-page text-muted hover:bg-brand-tint')}
                >
                  {t.label}
                  {count !== undefined && <span className="rounded-full bg-white/70 px-1.5 text-xs tabular-nums">{count}</span>}
                </button>
              )
            })}
          </div>
          {data?.sanitised && <p className="text-xs text-muted">You can see which of your requests have an order or an invoice. Supplier names, amounts and the documents themselves are for the staff who handle them.</p>}
        </div>
        <QueryState variant="table" columns={6} isLoading={isLoading} error={error} isEmpty={!data?.items.length} emptyMessage={q || kind ? 'No documents match.' : 'No documents yet.'}>
          <Table headers={staff ? ['Sr.No.', 'Document', 'Case', 'Supplier', 'Amount', 'Status', 'Date'] : ['Sr.No.', 'Document', 'Request', 'Date']}>
            {(data?.items ?? []).map((d, i) => {
              const Icon = KIND_ICON[d.kind] ?? FileSearch
              return (
                <Tr key={d.id}>
                  <Td first>{String((page - 1) * pageSize + i + 1).padStart(2, '0')}.</Td>
                  <Td>
                    <span className="inline-flex items-center gap-2 font-medium text-title"><Icon size={15} className="shrink-0 text-brand-ink" /> {d.title}</span>
                    <span className="block text-xs text-muted">{d.kind_label}</span>
                  </Td>
                  <Td className="whitespace-nowrap">
                    <Link to={caseLink(d.case_id)} className="font-medium tabular-nums text-brand-ink hover:underline">{d.case_number ?? d.case_id.slice(0, 8)}</Link>
                  </Td>
                  {staff && <Td>{d.vendor ?? '—'}</Td>}
                  {staff && <Td className="whitespace-nowrap tabular-nums">{d.amount !== null ? formatAmount(d.amount) : '—'}</Td>}
                  {staff && <Td>{d.status ?? '—'}</Td>}
                  <Td className="whitespace-nowrap">{d.at ? formatDateTime(d.at) : '—'}</Td>
                </Tr>
              )
            })}
          </Table>
        </QueryState>
        <Pagination page={page} pageSize={pageSize} totalItems={data?.total ?? 0} onPageChange={setPage} onPageSizeChange={(n) => { setPageSize(n); setPage(1) }} itemLabel="documents" />
      </Card>
    </div>
  )
}
