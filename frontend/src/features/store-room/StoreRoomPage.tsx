import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Download, Pencil, Search } from 'lucide-react'
import clsx from 'clsx'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { DEFAULT_PAGE_SIZE, Pagination } from '@/components/ui/Pagination'
import { QueryState } from '@/components/ui/QueryState'
import { useAuth } from '@/features/auth/AuthContext'
import { downloadCsv } from './api'
import { DatasetTable } from './DatasetTable'
import { useDatasetPage, useDebounced, useStoreRoomOverview } from './hooks'

// The Store Room only reads. Where the data is changed, a button leads there (shown to people who may).
const MANAGE: Record<string, { to: string; label: string; permission: string }> = {
  stock: { to: '/stock', label: 'Add / update stock', permission: 'stock:write' },
  suppliers: { to: '/vendors', label: 'Add / update suppliers', permission: 'vendors:write' },
}

const tab = (active: boolean) =>
  clsx(
    'inline-flex h-10 items-center gap-2 rounded-xl px-4 text-sm font-medium transition-colors',
    active ? 'bg-brand-soft text-brand-ink' : 'bg-white text-muted hover:bg-brand-tint',
  )

/** Read-only view of everything the system has stored: one table per topic. */
export function StoreRoomPage() {
  const { can } = useAuth()
  const overview = useStoreRoomOverview()
  const [params, setParams] = useSearchParams()

  const groups = overview.data?.groups ?? []
  const datasets = groups.flatMap((g) => g.datasets)

  // The chosen table lives in the URL, so a reload or a shared link lands on the same one.
  const active = datasets.find((d) => d.key === params.get('section')) ?? datasets[0]
  const activeGroup = groups.find((g) => g.datasets.some((d) => d.key === active?.key))

  const [searchText, setSearchText] = useState('')
  const search = useDebounced(searchText)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)

  const data = useDatasetPage(active?.key ?? '', search, page, pageSize, !!active)
  const manage = active ? MANAGE[active.key] : undefined

  function choose(key: string) {
    setParams({ section: key }, { replace: true })
    setSearchText('')
    setPage(1)
    setExportError(null)
  }

  async function onExport() {
    if (!active) return
    setExporting(true)
    setExportError(null)
    try {
      await downloadCsv(active.key, search)
    } catch (error) {
      setExportError(error instanceof Error ? error.message : 'Export failed')
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="flex w-full flex-col xl:h-full">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 pb-4">
        <h1 className="page-title">Store Room</h1>
        {manage && can(manage.permission) && (
          <Link to={manage.to}>
            <Button>
              <Pencil size={16} /> {manage.label}
            </Button>
          </Link>
        )}
      </div>

      {/* Topics: one tab each. A topic with several tables (e.g. Suppliers) shows them as small pills below. */}
      <div role="tablist" className="mb-3 flex shrink-0 flex-wrap gap-2">
        {groups.map((g) => (
          <button
            key={g.label}
            type="button"
            role="tab"
            aria-selected={activeGroup?.label === g.label}
            onClick={() => choose(g.datasets[0].key)}
            className={tab(activeGroup?.label === g.label)}
          >
            {g.label}
          </button>
        ))}
      </div>

      {activeGroup && activeGroup.datasets.length > 1 && (
        <div className="mb-3 flex shrink-0 flex-wrap gap-2">
          {activeGroup.datasets.map((d) => (
            <button
              key={d.key}
              type="button"
              onClick={() => choose(d.key)}
              className={clsx(
                'rounded-full px-3.5 py-1.5 text-xs font-semibold transition-colors',
                active?.key === d.key ? 'bg-brand text-white' : 'bg-white text-muted hover:bg-brand-tint',
              )}
            >
              {d.label} <span className="opacity-70">{d.count.toLocaleString()}</span>
            </button>
          ))}
        </div>
      )}

      {active && <p className="mb-3 shrink-0 text-sm text-muted">{active.description}</p>}

      <Card className="flex-1" bodyClassName="flex min-h-0 flex-col p-0">
        <div className="flex shrink-0 flex-wrap items-center gap-3 border-b border-line px-5 py-3">
          <div className="relative min-w-[220px] flex-1 sm:max-w-xs">
            <Search size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" />
            <input
              value={searchText}
              onChange={(e) => {
                setSearchText(e.target.value)
                setPage(1)
              }}
              placeholder={`Search ${active?.label.toLowerCase() ?? ''}`}
              aria-label="Search"
              maxLength={100}
              className="h-10 w-full rounded-xl border border-line pl-10 pr-3 text-sm focus:border-brand focus:outline-none focus:ring-4 focus:ring-brand/15"
            />
          </div>
          <div className="ml-auto flex items-center gap-3">
            {exportError && <span className="text-sm text-danger">{exportError}</span>}
            <Button variant="secondary" loading={exporting} onClick={() => void onExport()} disabled={!data.data?.total}>
              <Download size={16} /> Export CSV
            </Button>
          </div>
        </div>

        <QueryState
          variant="table"
          columns={6}
          isLoading={overview.isLoading || data.isLoading}
          error={overview.error ?? data.error}
          isEmpty={!data.data?.rows.length}
          emptyMessage={search ? `Nothing matches “${search}”.` : 'Nothing stored here yet.'}
        >
          {data.data && <DatasetTable columns={data.data.columns} rows={data.data.rows} offset={(page - 1) * pageSize} />}
        </QueryState>

        <Pagination
          page={page}
          pageSize={pageSize}
          totalItems={data.data?.total ?? 0}
          onPageChange={setPage}
          onPageSizeChange={(n) => {
            setPageSize(n)
            setPage(1)
          }}
          itemLabel="records"
        />
      </Card>
    </div>
  )
}
