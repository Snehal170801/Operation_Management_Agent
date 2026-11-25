import { useState } from 'react'
import { RefreshCw, Search } from 'lucide-react'
import clsx from 'clsx'
import { Card } from '@/components/ui/Card'
import { DEFAULT_PAGE_SIZE, Pagination } from '@/components/ui/Pagination'
import { QueryState } from '@/components/ui/QueryState'
import { Table, Td, Tr } from '@/components/ui/Table'
import { formatDateTime, humanize } from '@/lib/format'
import { useAudit } from '../api'

const TONE: Record<string, string> = {
  success: 'bg-[#DCFCE7] text-[#16A34A]',
  failure: 'bg-amber-100 text-amber-700',
  denied: 'bg-danger-soft text-danger',
}

const select =
  'h-10 rounded-xl border border-line bg-white px-3 text-sm focus:border-brand focus:outline-none'

function summarize(detail: Record<string, unknown> | null): string {
  if (!detail) return ''
  return Object.entries(detail)
    .map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : String(v)}`)
    .join(' · ')
}

export function AuditPage() {
  const [search, setSearch] = useState('')
  const [action, setAction] = useState('')
  const [outcome, setOutcome] = useState('')
  const [days, setDays] = useState('7')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)

  const { data, isLoading, error, isFetching, refetch } = useAudit({
    limit: pageSize,
    offset: (page - 1) * pageSize,
    action,
    outcome,
    search,
    days,
  })
  const filter = <T,>(set: (v: T) => void) => (v: T) => {
    set(v)
    setPage(1)
  }

  return (
    <div className="flex w-full flex-col xl:h-full">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 pb-4">
        <h1 className="page-title">Audit Log</h1>
        <button
          type="button"
          onClick={() => void refetch()}
          className="inline-flex h-10 items-center gap-2 rounded-xl border border-line bg-white px-4 text-sm font-medium text-title hover:bg-brand-tint"
        >
          <RefreshCw size={15} className={clsx(isFetching && 'animate-spin')} /> Refresh
        </button>
      </div>

      <Card className="flex-1" bodyClassName="flex min-h-0 flex-col p-0">
        <div className="flex shrink-0 flex-wrap items-center gap-3 border-b border-line px-5 py-3">
          <div className="relative min-w-55 flex-1 sm:max-w-xs">
            <Search size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" />
            <input
              value={search}
              onChange={(e) => filter(setSearch)(e.target.value)}
              placeholder="Search user, target or details"
              className="h-10 w-full rounded-xl border border-line pl-10 pr-3 text-sm focus:border-brand focus:outline-none focus:ring-4 focus:ring-brand/15"
            />
          </div>
          <select className={select} value={action} onChange={(e) => filter(setAction)(e.target.value)} aria-label="Event type">
            <option value="">All events</option>
            <option value="auth.">Sign-in &amp; passwords</option>
            <option value="user.">User changes</option>
            <option value="role.">Role changes</option>
            <option value="authz.">Access denied</option>
          </select>
          <select className={select} value={outcome} onChange={(e) => filter(setOutcome)(e.target.value)} aria-label="Outcome">
            <option value="">Any outcome</option>
            <option value="success">Success</option>
            <option value="failure">Failure</option>
            <option value="denied">Denied</option>
          </select>
          <select className={select} value={days} onChange={(e) => filter(setDays)(e.target.value)} aria-label="Time range">
            <option value="1">Last 24 hours</option>
            <option value="7">Last 7 days</option>
            <option value="30">Last 30 days</option>
            <option value="">All time</option>
          </select>
        </div>

        <QueryState variant="table" columns={7} isLoading={isLoading} error={error} isEmpty={!data?.items.length} emptyMessage="No events match these filters.">
          <Table stackBelow="xl" headers={['Time', 'Who', 'Event', 'Outcome', 'Target', 'IP', 'Details']}>
            {data?.items.map((e) => (
              <Tr key={e.audit_id}>
                <Td first className="whitespace-nowrap">{formatDateTime(e.created_at)}</Td>
                <Td className="max-w-50 truncate" >{e.actor_username ?? '—'}</Td>
                <Td className="whitespace-nowrap font-medium">{humanize(e.action)}</Td>
                <Td>
                  <span className={clsx('inline-flex rounded-full px-2.5 py-1 text-[11px] font-semibold', TONE[e.outcome] ?? 'bg-slate-100 text-slate-600')}>
                    {humanize(e.outcome)}
                  </span>
                </Td>
                <Td className="max-w-45 truncate">{e.target_id ? `${e.target_type ?? ''} ${e.target_id}`.trim() : '—'}</Td>
                <Td className="whitespace-nowrap tabular-nums text-xs">{e.ip_address ?? '—'}</Td>
                <Td className="max-w-80 truncate text-xs text-muted" >
                  <span title={summarize(e.detail)}>{summarize(e.detail) || '—'}</span>
                </Td>
              </Tr>
            ))}
          </Table>
        </QueryState>

        <Pagination
          page={page}
          pageSize={pageSize}
          totalItems={data?.total ?? 0}
          onPageChange={setPage}
          onPageSizeChange={(n) => {
            setPageSize(n)
            setPage(1)
          }}
          itemLabel="events"
        />
      </Card>
    </div>
  )
}
