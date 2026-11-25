import { useState, type ReactNode } from 'react'
import { Bot, ClipboardList, Clock, IndianRupee, Package, TriangleAlert, UserRound } from 'lucide-react'
import clsx from 'clsx'
import { Card } from '@/components/ui/Card'
import { QueryState } from '@/components/ui/QueryState'
import { StatTile } from '@/components/ui/StatTile'
import { formatAmount, formatAmountShort } from '@/lib/format'
import { useReport } from './hooks'
import type { Report, SupplierScore } from './types'

const PERIODS = [
  { days: 7, label: '7 days' },
  { days: 30, label: '30 days' },
  { days: 90, label: '90 days' },
  { days: 0, label: 'All time' },
] as const

/** "35 min", "6.5 h", "2.4 days": whichever reads best. */
function duration(hours: number | null): string {
  if (hours === null) return '—'
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))} min`
  if (hours < 48) return `${hours.toFixed(1)} h`
  return `${(hours / 24).toFixed(1)} days`
}

const monthName = (key: string) => new Date(`${key}-01T00:00:00`).toLocaleDateString('en-IN', { month: 'short', year: 'numeric' })
const pct = (v: number | null) => (v === null ? '—' : `${v}%`)

function Bar({ value, max, tone = 'bg-brand' }: { value: number; max: number; tone?: string }) {
  return (
    <div className="h-2.5 w-full overflow-hidden rounded-full bg-line">
      <div className={clsx('h-full rounded-full', tone)} style={{ width: `${max > 0 ? Math.max(3, (value / max) * 100) : 0}%` }} />
    </div>
  )
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-xl bg-brand-tint px-4 py-3 text-sm text-muted">{children}</p>
}

function AutomationCard({ a }: { a: Report['automation'] }) {
  const total = a.touchless + a.needed_a_person
  const pctValue = a.touchless_pct ?? 0
  const worst = a.by_agent[0]?.cases ?? 0
  return (
    <Card title="How much ran by itself" bodyClassName="p-5">
      {total === 0 ? (
        <Empty>No request has finished yet in this period, so there is nothing to compare.</Empty>
      ) : (
        <div className="flex flex-col gap-6">
          <div className="flex flex-wrap items-center gap-6">
            <div
              className="grid h-28 w-28 shrink-0 place-items-center rounded-full"
              style={{ background: `conic-gradient(#16A34A ${pctValue * 3.6}deg, #fdecec 0)` }}
              role="img"
              aria-label={`${pctValue} percent ran with no person`}
            >
              <div className="grid h-[84px] w-[84px] place-items-center rounded-full bg-white">
                <span className="text-2xl font-semibold tabular-nums text-title">{pctValue}%</span>
              </div>
            </div>
            <ul className="flex flex-col gap-2 text-sm">
              <li className="flex items-center gap-2">
                <Bot size={16} className="text-[#16A34A]" />
                <b className="tabular-nums">{a.touchless}</b> ran start to finish with no person
              </li>
              <li className="flex items-center gap-2">
                <UserRound size={16} className="text-amber-600" />
                <b className="tabular-nums">{a.needed_a_person}</b> needed a person at least once
              </li>
              {a.in_progress_so_far_clean > 0 && (
                <li className="flex items-center gap-2 text-muted">
                  <Clock size={16} /> {a.in_progress_so_far_clean} still in progress, no person needed so far
                </li>
              )}
            </ul>
          </div>

          {a.by_agent.length > 0 && (
            <div>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Where a person was needed</h3>
              <ul className="flex flex-col gap-3">
                {a.by_agent.map((agent) => (
                  <li key={agent.agent}>
                    <div className="flex items-baseline justify-between gap-3 text-sm">
                      <span className="font-semibold text-title">{agent.agent} agent</span>
                      <span className="tabular-nums text-muted">{agent.cases} request{agent.cases === 1 ? '' : 's'}</span>
                    </div>
                    <Bar value={agent.cases} max={worst} tone="bg-amber-500" />
                    <ul className="mt-1.5 text-xs text-muted">
                      {agent.reasons.map((r) => (
                        <li key={r.label}>
                          {r.label} <span className="tabular-nums">· {r.cases}</span>
                        </li>
                      ))}
                    </ul>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Card>
  )
}

function SpendCard({ spend }: { spend: Report['spend'] }) {
  const topVendor = Math.max(0, ...spend.by_vendor.map((v) => v.total))
  const topMonth = Math.max(0, ...spend.by_month.map((m) => m.total))
  return (
    <Card title="Spend" action={`${formatAmount(spend.total)} on ${spend.orders} order${spend.orders === 1 ? '' : 's'}`} bodyClassName="p-5">
      {spend.orders === 0 ? (
        <Empty>No orders have been placed in this period.</Empty>
      ) : (
        <div className="grid gap-6 lg:grid-cols-2">
          <div>
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted">By month</h3>
            <div className="flex h-40 items-end gap-3">
              {spend.by_month.map((m) => (
                <div key={m.month} className="flex min-w-0 flex-1 flex-col items-center justify-end gap-1" title={`${formatAmount(m.total)} · ${m.orders} orders`}>
                  <span className="text-[11px] font-medium tabular-nums text-muted">{formatAmountShort(m.total)}</span>
                  <div className="w-full max-w-14 rounded-t-lg bg-brand" style={{ height: `${Math.max(4, (m.total / topMonth) * 100)}px` }} />
                  <span className="text-[11px] text-muted">{monthName(m.month)}</span>
                </div>
              ))}
            </div>
          </div>
          <div>
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted">By supplier</h3>
            <ul className="flex flex-col gap-3">
              {spend.by_vendor.slice(0, 8).map((v) => (
                <li key={v.vendor}>
                  <div className="flex items-baseline justify-between gap-3 text-sm">
                    <span className="truncate font-medium text-title">{v.vendor}</span>
                    <span className="shrink-0 tabular-nums text-muted">
                      {formatAmount(v.total)} · {v.orders}
                    </span>
                  </div>
                  <Bar value={v.total} max={topVendor} />
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </Card>
  )
}

function StagesCard({ stages }: { stages: Report['stage_times'] }) {
  const top = Math.max(0, ...stages.map((s) => s.avg_hours ?? 0))
  return (
    <Card title="How long each stage takes" action="average" bodyClassName="p-5">
      {stages.every((s) => s.count === 0) ? (
        <Empty>Not enough finished steps yet to work out timings.</Empty>
      ) : (
        <ul className="flex flex-col gap-4">
          {stages.map((s, i) => (
            <li key={s.label}>
              <div className="flex items-baseline justify-between gap-3 text-sm">
                <span className={clsx('min-w-0', i === stages.length - 1 ? 'font-semibold text-title' : 'text-title')}>{s.label}</span>
                <span className="shrink-0 tabular-nums">
                  <b>{duration(s.avg_hours)}</b> <span className="text-xs text-muted">· {s.count} request{s.count === 1 ? '' : 's'}</span>
                </span>
              </div>
              <Bar value={s.avg_hours ?? 0} max={top} tone={i === stages.length - 1 ? 'bg-slate-700' : 'bg-brand'} />
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function StuckCard({ stuck }: { stuck: Report['stuck'] }) {
  return (
    <Card title="Open requests: where they are waiting" bodyClassName="p-0">
      {stuck.length === 0 ? (
        <p className="px-5 py-5 text-sm text-emerald-700">Nothing is open in this period.</p>
      ) : (
        <ul className="divide-y divide-line">
          {stuck.map((s) => (
            <li key={s.stage} className="flex items-center justify-between gap-4 px-5 py-3 text-sm">
              <span className="min-w-0 text-title">{s.label}</span>
              <span className="flex shrink-0 items-center gap-3 tabular-nums">
                <span className="rounded-full bg-brand-soft px-2.5 py-0.5 text-xs font-semibold text-brand-ink">{s.count}</span>
                <span className={clsx('text-xs', s.oldest_hours > 24 ? 'font-semibold text-danger' : 'text-muted')}>oldest {duration(s.oldest_hours)}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function SupplierRow({ s }: { s: SupplierScore }) {
  const worry = (s.reply_rate !== null && s.reply_rate < 50) || s.late > 0 || s.invoice_problems > 0
  return (
    <tr className="border-t border-line align-top text-sm">
      <td className="px-4 py-3 font-medium text-title">
        {s.name} {worry && <TriangleAlert size={13} className="ml-1 inline text-amber-600" aria-label="Needs a look" />}
      </td>
      <td className="px-3 py-3 tabular-nums">{s.replied}/{s.asked} <span className="text-muted">({pct(s.reply_rate)})</span></td>
      <td className="px-3 py-3 tabular-nums">{duration(s.avg_reply_hours)}</td>
      <td className="px-3 py-3 tabular-nums">{s.orders ? `${s.orders} · ${formatAmountShort(s.spend)}` : '—'}</td>
      <td className="px-3 py-3 tabular-nums">{pct(s.confirm_rate)}{s.avg_confirm_hours !== null && <span className="text-muted"> · {duration(s.avg_confirm_hours)}</span>}</td>
      <td className={clsx('px-3 py-3 tabular-nums', s.late > 0 && 'text-danger')}>
        {s.orders ? `${s.late} late` : '—'}
        {s.avg_days_late !== null && <span className="text-muted"> · avg {s.avg_days_late.toFixed(1)} d</span>}
      </td>
      <td className={clsx('px-3 py-3 tabular-nums', s.invoice_problems > 0 && 'text-danger')}>{s.invoices ? `${s.invoice_problems}/${s.invoices}` : '—'}</td>
    </tr>
  )
}

function SuppliersCard({ suppliers }: { suppliers: SupplierScore[] }) {
  return (
    <Card title="Supplier scorecards" action="biggest spend first" bodyClassName="p-0">
      {suppliers.length === 0 ? (
        <div className="p-5">
          <Empty>No supplier has been asked for a quote in this period.</Empty>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-left">
            <thead className="bg-brand-tint/60 text-xs font-semibold uppercase tracking-wide text-muted">
              <tr>
                <th className="px-4 py-2.5">Supplier</th>
                <th className="px-3 py-2.5">Replied to quote requests</th>
                <th className="px-3 py-2.5">Reply time</th>
                <th className="px-3 py-2.5">Orders · spend</th>
                <th className="px-3 py-2.5">Confirmed the order</th>
                <th className="px-3 py-2.5">Deliveries</th>
                <th className="px-3 py-2.5">Invoice problems</th>
              </tr>
            </thead>
            <tbody>
              {suppliers.map((s) => (
                <SupplierRow key={s.vendor_id} s={s} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

/** What a manager asks first: what did we spend, how long does it take, how much runs without anyone, and who is reliable. */
export function ReportsPage() {
  const [days, setDays] = useState<number>(90)
  const report = useReport(days)
  const r = report.data

  return (
    <div className="flex w-full flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="page-title">Reports</h1>
        <div role="group" aria-label="Period" className="flex rounded-xl border border-line bg-white p-1">
          {PERIODS.map((p) => (
            <button
              key={p.days}
              type="button"
              aria-pressed={days === p.days}
              onClick={() => setDays(p.days)}
              className={clsx('h-9 rounded-lg px-3.5 text-sm font-medium', days === p.days ? 'bg-brand-soft text-brand-ink' : 'text-muted hover:bg-brand-tint')}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>
      <p className="-mt-2 text-sm text-muted">Requests started in the {days === 0 ? 'whole history' : `last ${days} days`}. Everything here is worked out from what the agents already recorded.</p>

      <QueryState variant="cards" isLoading={report.isLoading} error={report.error} isEmpty={false}>
        {r && (
          <>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <StatTile icon={<ClipboardList size={20} />} label="Requests" value={r.totals.requests} note={`${r.totals.completed} completed · ${r.totals.in_progress} open`} />
              <StatTile icon={<IndianRupee size={20} />} label="Spend" value={formatAmountShort(r.totals.spend)} note={`${r.totals.orders} order${r.totals.orders === 1 ? '' : 's'}`} />
              <StatTile icon={<Package size={20} />} label="Filled from stock" value={r.totals.from_stock} note={r.totals.rejected || r.totals.cancelled ? `${r.totals.rejected} not approved · ${r.totals.cancelled} cancelled` : 'No order needed'} />
              <StatTile icon={<Clock size={20} />} label="Average time to complete" value={duration(r.totals.avg_cycle_hours)} note="request to invoice cleared" />
            </div>

            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              <AutomationCard a={r.automation} />
              <StagesCard stages={r.stage_times} />
            </div>
            <SpendCard spend={r.spend} />
            <StuckCard stuck={r.stuck} />
            <SuppliersCard suppliers={r.suppliers} />
          </>
        )}
      </QueryState>
    </div>
  )
}
