import { Link } from 'react-router-dom'
import {
  AlertTriangle,
  Boxes,
  ClipboardCheck,
  ClipboardList,
  PackageOpen,
  ShieldAlert,
  Truck,
  Wallet,
} from 'lucide-react'
import clsx from 'clsx'
import { Card } from '@/components/ui/Card'
import { QueryState } from '@/components/ui/QueryState'
import { LiveStatus } from '@/components/ui/LiveStatus'
import { StatTile } from '@/components/ui/StatTile'
import { formatAmount, formatAmountShort, formatDateTime, humanize } from '@/lib/format'
import { formatDuration, parseUtc, timeAgo, useNow } from '@/lib/time'
import { useDashboard } from './hooks'
import type { DashboardSnapshot } from './types'

/** The live operations dashboard. Used on the Dashboard page and as the Store Room overview. */
export function LiveDashboard() {
  const { data, isLoading, error, isFetching, dataUpdatedAt, isError } = useDashboard()
  const now = useNow()

  return (
    <div className="flex w-full flex-col gap-4">
      <LiveStatus updatedAt={dataUpdatedAt} fetching={isFetching} failed={isError && !!data} now={now} />

      {data?.automation_paused && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-amber-300 bg-amber-50 px-5 py-3 text-sm text-amber-800">
          <span className="font-medium">Automation is paused. The agents are idle and new requests are being held.</span>
          <Link to="/settings?tab=automation" className="font-semibold underline">
            Manage
          </Link>
        </div>
      )}

      {error && !data && <p className="text-sm text-danger">{error.message}</p>}

      {data?.attention.length ? <NeedsAttention items={data.attention} /> : null}

      <Tiles data={data} loading={isLoading} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <StageCard data={data} loading={isLoading} error={error} />
        <TrendCard data={data} />
        <StockCard data={data} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <AutomationCard data={data} />
        <ActivityCard data={data} loading={isLoading} error={error} now={now} />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------------------------

function NeedsAttention({ items }: { items: DashboardSnapshot['attention'] }) {
  return (
    <Card
      title="Needs attention"
      className="border-danger/30"
      bodyClassName="p-0"
      action={`${items.length} item${items.length === 1 ? '' : 's'}`}
    >
      <ul className="divide-y divide-line">
        {items.map((n) => (
          <li key={n.id} className="dash-fade-in">
            <Link to={n.link} className="flex items-center gap-3 px-5 py-3 hover:bg-brand-tint/60">
              <AlertTriangle size={18} className="shrink-0 text-danger" />
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-semibold text-title">{n.title}</span>
                <span className="block truncate text-xs text-muted">{n.message}</span>
              </span>
              <span className="shrink-0 text-xs text-muted">{formatDateTime(n.created_at)}</span>
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  )
}

function Tiles({ data, loading }: { data?: DashboardSnapshot; loading: boolean }) {
  const t = data?.totals
  const s = data?.spend
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-6">
      <StatTile loading={loading} icon={<ClipboardList size={22} />} label="Open cases" value={t?.cases_open ?? 0}
        note={`${t?.cases_closed ?? 0} closed · ${t?.cases_total ?? 0} total`} />
      <StatTile loading={loading} icon={<ShieldAlert size={22} />} label="Needs attention" value={t?.needs_attention ?? 0}
        note={t?.needs_attention ? 'A person is needed' : 'All clear'} noteTone={t?.needs_attention ? 'bad' : 'good'} />
      <StatTile loading={loading} icon={<ClipboardCheck size={22} />} label="Awaiting approval" value={t?.pending_approvals ?? 0}
        note={t?.pending_approvals ? 'Waiting for a decision' : 'Nothing waiting'} noteTone={t?.pending_approvals ? 'bad' : 'good'} />
      <StatTile loading={loading} icon={<Truck size={22} />} label="Awaiting delivery" value={t?.awaiting_delivery ?? 0}
        note={t?.overdue_deliveries ? `${t.overdue_deliveries} overdue` : 'None overdue'} noteTone={t?.overdue_deliveries ? 'bad' : 'good'} />
      <StatTile loading={loading} icon={<Boxes size={22} />} label="Stock items" value={t?.stock_items ?? 0}
        note={`${t?.out_of_stock ?? 0} out · ${t?.low_stock ?? 0} low`} noteTone={t?.out_of_stock ? 'bad' : 'muted'} />
      <StatTile loading={loading} icon={<Wallet size={22} />} label="Ordered today" value={formatAmountShort(s?.ordered_today ?? 0)}
        note={`${formatAmountShort(s?.ordered_total ?? 0)} ordered in all`} />
    </div>
  )
}

function StageCard({ data, loading, error }: { data?: DashboardSnapshot; loading: boolean; error: Error | null }) {
  const stages = data?.by_stage ?? []
  const max = Math.max(1, ...stages.map((s) => s.count))
  return (
    <Card title="Open cases by stage">
      <QueryState variant="list" rows={4} isLoading={loading} error={error} isEmpty={!stages.length} emptyMessage="No open cases right now.">
        <ul className="flex flex-col gap-4">
          {stages.map(({ stage, count }) => (
            <li key={stage}>
              <div className="mb-1.5 flex justify-between text-xs">
                <span className="font-medium text-title">{humanize(stage)}</span>
                <span className="tabular-nums text-muted">{count}</span>
              </div>
              <div className="h-2 rounded-full bg-brand-tint">
                <div
                  className="h-2 rounded-full bg-[linear-gradient(135deg,#c53536_0%,#ea4d4e_100%)] transition-[width] duration-500"
                  style={{ width: `${(count / max) * 100}%` }}
                />
              </div>
            </li>
          ))}
        </ul>
      </QueryState>
    </Card>
  )
}

function TrendCard({ data }: { data?: DashboardSnapshot }) {
  const days = data?.created_per_day ?? []
  const max = Math.max(1, ...days.map((d) => d.count))
  const total = days.reduce((sum, d) => sum + d.count, 0)
  return (
    <Card title="New requests, last 7 days" action={`${total} total`}>
      <div className="flex h-32 items-end gap-2" role="img" aria-label={`New requests per day: ${days.map((d) => d.count).join(', ')}`}>
        {days.map((d) => (
          <div key={d.day} className="flex h-full flex-1 flex-col items-center justify-end gap-1">
            <span className="text-[10px] tabular-nums text-muted">{d.count || ''}</span>
            <div
              className="w-full rounded-t-md bg-[linear-gradient(135deg,#c53536_0%,#ea4d4e_100%)] transition-[height] duration-500"
              style={{ height: `${Math.max(d.count ? 8 : 2, (d.count / max) * 80)}%`, opacity: d.count ? 1 : 0.25 }}
            />
          </div>
        ))}
      </div>
      <div className="mt-2 flex gap-2">
        {days.map((d) => (
          <span key={d.day} className="flex-1 text-center text-[10px] text-muted">
            {new Date(`${d.day}T00:00:00`).toLocaleDateString(undefined, { weekday: 'short' })}
          </span>
        ))}
      </div>
    </Card>
  )
}

function StockCard({ data }: { data?: DashboardSnapshot }) {
  const t = data?.totals
  const total = t?.stock_items ?? 0
  const out = t?.out_of_stock ?? 0
  const low = t?.low_stock ?? 0
  const ok = Math.max(0, total - out - low)
  const parts = [
    { label: 'In stock', n: ok, color: 'bg-[#16A34A]' },
    { label: 'Low', n: low, color: 'bg-amber-500' },
    { label: 'Out of stock', n: out, color: 'bg-danger' },
  ]
  return (
    <Card
      title="Stock health"
      action={
        <Link to="/store-room?section=stock" className="font-medium text-brand-ink hover:underline">
          Open stock
        </Link>
      }
    >
      <div className="flex h-3 overflow-hidden rounded-full bg-brand-tint" role="img" aria-label={parts.map((p) => `${p.label}: ${p.n}`).join(', ')}>
        {total > 0 &&
          parts.map((p) => (
            <div key={p.label} className={clsx(p.color, 'transition-[width] duration-500')} style={{ width: `${(p.n / total) * 100}%` }} />
          ))}
      </div>
      <ul className="mt-4 flex flex-col gap-2.5 text-sm">
        {parts.map((p) => (
          <li key={p.label} className="flex items-center justify-between">
            <span className="flex items-center gap-2 text-title">
              <span className={clsx('h-2.5 w-2.5 rounded-full', p.color)} /> {p.label}
            </span>
            <span className="tabular-nums text-muted">{p.n}</span>
          </li>
        ))}
      </ul>
      {out + low > 0 && (
        <p className="mt-3 flex items-center gap-1.5 text-xs text-muted">
          <PackageOpen size={14} /> {out + low} item{out + low === 1 ? '' : 's'} may need re-ordering.
        </p>
      )}
    </Card>
  )
}

function AutomationCard({ data }: { data?: DashboardSnapshot }) {
  const s = data?.spend
  const r = data?.rates
  const used = s && s.daily_limit > 0 ? Math.min(100, (s.auto_approved_today / s.daily_limit) * 100) : 0
  return (
    <Card title="Automation">
      <dl className="grid grid-cols-2 gap-4 text-sm">
        <div>
          <dt className="text-xs text-muted">Approved with no person</dt>
          <dd className="text-2xl font-semibold text-title">
            {r?.auto_approval_percent != null ? `${r.auto_approval_percent}%` : '—'}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Average time to close</dt>
          <dd className="text-2xl font-semibold text-title">{formatDuration(r?.avg_close_minutes)}</dd>
        </div>
      </dl>
      <div className="mt-5">
        <div className="mb-1.5 flex justify-between text-xs">
          <span className="font-medium text-title">Automatic spend today</span>
          <span className="tabular-nums text-muted">
            {formatAmount(s?.auto_approved_today ?? 0)} of {formatAmount(s?.daily_limit ?? 0)}
          </span>
        </div>
        <div className="h-2 rounded-full bg-brand-tint">
          <div
            className={clsx('h-2 rounded-full transition-[width] duration-500', used >= 90 ? 'bg-danger' : 'bg-[#16A34A]')}
            style={{ width: `${used}%` }}
          />
        </div>
        <p className="mt-1.5 text-xs text-muted">Over the daily limit, a person has to approve.</p>
      </div>
    </Card>
  )
}

function ActivityCard({ data, loading, error, now }: { data?: DashboardSnapshot; loading: boolean; error: Error | null; now: number }) {
  const items = data?.activity ?? []
  return (
    <Card className="lg:col-span-2" title="Live activity" action="What the agents just did" bodyClassName="p-0">
      <QueryState variant="list" rows={5} isLoading={loading} error={error} isEmpty={!items.length} emptyMessage="No activity yet.">
        <ul className="divide-y divide-line">
          {items.map((e) => (
            // Stable key: only a genuinely new event mounts, so only new rows play the fade-in.
            <li key={e.event_id} className="dash-fade-in">
              <Link to={`/cases/${e.case_id}`} className="flex items-center gap-3 px-5 py-2.5 hover:bg-brand-tint/60">
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-title">{humanize(e.event_type)}</span>
                  <span className="block truncate text-xs text-muted">
                    {e.agent_name ?? 'System'} · {e.case_number ?? `case ${e.case_id.slice(0, 8).toLowerCase()}`}
                  </span>
                </span>
                <span className="shrink-0 text-xs text-muted">{timeAgo(parseUtc(e.created_at), now)}</span>
              </Link>
            </li>
          ))}
        </ul>
      </QueryState>
    </Card>
  )
}
