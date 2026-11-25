import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, Search } from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { useAuth } from '@/features/auth/AuthContext'
import { Card } from '@/components/ui/Card'
import { DEFAULT_PAGE_SIZE, Pagination } from '@/components/ui/Pagination'
import { QueryState } from '@/components/ui/QueryState'
import { Table, Td, Tr } from '@/components/ui/Table'
import { formatDateTime } from '@/lib/format'
import { DownloadExportButton } from '@/features/exports/DownloadExportButton'
import { CreateCaseModal } from '../components/CreateCaseForm'
import { useCases } from '../hooks'

export function CasesPage() {
  const { can } = useAuth()
  const { data, isLoading, error } = useCases()
  const navigate = useNavigate()
  const [creating, setCreating] = useState(false)
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('all')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return (data ?? []).filter(
      (c) =>
        (status === 'all' || c.status === status) &&
        (!q || [c.case_number ?? '', c.case_id, c.requester_id, c.items_summary ?? ''].some((v) => v.toLowerCase().includes(q))),
    )
  }, [data, search, status])

  const rows = filtered.slice((page - 1) * pageSize, page * pageSize)

  return (
    <div className="flex w-full flex-col xl:h-full">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 pb-4">
        <h1 className="page-title">Cases</h1>
        <div className="flex flex-wrap items-start gap-2">
          <DownloadExportButton kind="cases" label="CSV" />
          <DownloadExportButton kind="cases" format="xlsx" label="Excel" />
          {can('cases:write') && (
            <Button onClick={() => setCreating(true)}>
              <Plus size={18} /> New case
            </Button>
          )}
        </div>
      </div>

      <Card className="flex-1" bodyClassName="flex min-h-0 flex-col p-0">
        <div className="flex shrink-0 flex-wrap items-center gap-3 border-b border-line px-5 py-3">
          <div className="relative min-w-[220px] flex-1 sm:max-w-xs">
            <Search size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" />
            <input
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(1) }}
              placeholder="Search case number, requester or item"
              className="h-10 w-full rounded-xl border border-line pl-10 pr-3 text-sm focus:border-brand focus:outline-none focus:ring-4 focus:ring-brand/15"
            />
          </div>
          <select
            value={status}
            onChange={(e) => { setStatus(e.target.value); setPage(1) }}
            className="h-10 rounded-xl border border-line bg-white px-3 text-sm focus:border-brand focus:outline-none"
          >
            <option value="all">All statuses</option>
            <option value="open">Open</option>
            <option value="closed">Closed</option>
            <option value="rejected">Rejected</option>
          </select>
        </div>

        <QueryState variant="table" columns={7} isLoading={isLoading} error={error} isEmpty={!filtered.length} emptyMessage="No cases found.">
          <Table headers={['Sr.No.', 'Case', 'Requester', 'Items', 'Stage', 'Status', 'Updated']}>
            {rows.map((c, i) => (
              <Tr key={c.case_id} onClick={() => navigate(`/cases/${c.case_id}`)}>
                <Td first>{String((page - 1) * pageSize + i + 1).padStart(2, '0')}.</Td>
                <Td className="whitespace-nowrap font-medium tabular-nums">{c.case_number ?? c.case_id.slice(0, 8)}</Td>
                <Td>{c.requester_id}</Td>
                <Td className="max-w-[260px] truncate">{c.items_summary ?? '—'}</Td>
                <Td><Badge value={c.stage} /></Td>
                <Td><Badge value={c.status} /></Td>
                <Td>{formatDateTime(c.updated_at)}</Td>
              </Tr>
            ))}
          </Table>
        </QueryState>

        <Pagination
          page={page}
          pageSize={pageSize}
          totalItems={filtered.length}
          onPageChange={setPage}
          onPageSizeChange={(n) => { setPageSize(n); setPage(1) }}
          itemLabel="cases"
        />
      </Card>

      <CreateCaseModal open={creating} onClose={() => setCreating(false)} />
    </div>
  )
}
