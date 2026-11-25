import { Activity, Database, RefreshCw, Sparkles } from 'lucide-react'
import clsx from 'clsx'
import { Card } from '@/components/ui/Card'
import { QueryState } from '@/components/ui/QueryState'
import { StatTile } from '@/components/ui/StatTile'
import { formatDateTime } from '@/lib/format'
import { useSystemHealth, type CheckStatus } from '../system'

const TONE: Record<CheckStatus, { dot: string; pill: string; label: string }> = {
  ok: { dot: 'bg-[#16A34A]', pill: 'bg-[#DCFCE7] text-[#16A34A]', label: 'Healthy' },
  warning: { dot: 'bg-amber-500', pill: 'bg-amber-100 text-amber-700', label: 'Degraded' },
  down: { dot: 'bg-danger', pill: 'bg-danger-soft text-danger', label: 'Down' },
}

const CHECK_ICON: Record<string, typeof Activity> = { API: Activity, Database, 'Azure OpenAI': Sparkles }

function formatUptime(seconds: number): string {
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m ${seconds % 60}s`
}

export function SystemHealthSection() {
  const { data, isLoading, error, isFetching } = useSystemHealth(true)

  return (
    <div className="flex flex-col gap-4">
      <Card
        title="System health"
        action={
          <span className="inline-flex items-center gap-1.5">
            <RefreshCw size={12} className={clsx(isFetching && 'animate-spin')} /> Auto-refreshes every 10s
          </span>
        }
      >
        <QueryState variant="cards" rows={3} isLoading={isLoading} error={error} isEmpty={!data}>
          {data && (
            <>
              <div className="mb-5 flex items-center gap-3">
                <span className={clsx('inline-flex items-center gap-2 rounded-full px-3 py-1 text-sm font-semibold', TONE[data.status].pill)}>
                  <span className={clsx('h-2 w-2 rounded-full', TONE[data.status].dot)} />
                  {TONE[data.status].label}
                </span>
                <span className="text-xs text-muted">Checked {formatDateTime(data.checked_at)}</span>
              </div>

              <ul className="grid grid-cols-1 gap-3 md:grid-cols-3">
                {data.checks.map((check) => {
                  const Icon = CHECK_ICON[check.name] ?? Activity
                  const tone = TONE[check.status]
                  return (
                    <li key={check.name} className="flex items-start gap-3 rounded-xl border border-line p-4">
                      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-soft text-brand-ink">
                        <Icon size={20} />
                      </span>
                      <div className="min-w-0">
                        <p className="flex items-center gap-2 text-sm font-semibold text-title">
                          {check.name}
                          <span className={clsx('h-2 w-2 rounded-full', tone.dot)} aria-label={tone.label} />
                        </p>
                        <p className="text-xs text-muted">{check.detail}</p>
                        {check.latency_ms != null && <p className="mt-1 text-xs text-muted">{check.latency_ms} ms</p>}
                      </div>
                    </li>
                  )
                })}
              </ul>
            </>
          )}
        </QueryState>
      </Card>

      {data?.stats && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatTile icon={<Activity size={22} />} label="Active sessions" value={data.stats.active_sessions} />
          <StatTile icon={<Activity size={22} />} label="Users" value={data.stats.users} />
          <StatTile icon={<Activity size={22} />} label="Cases" value={data.stats.cases} note={`${data.stats.open_cases} open`} />
          <StatTile icon={<Database size={22} />} label="Migrations applied" value={data.stats.migrations_applied} />
        </div>
      )}

      {data && (
        <Card title="Environment">
          <dl className="grid grid-cols-[10rem_1fr] gap-y-2.5 text-sm">
            <dt className="text-muted">Environment</dt><dd className="text-title">{data.info.environment}</dd>
            <dt className="text-muted">Database</dt><dd className="text-title">{data.info.database}</dd>
            <dt className="text-muted">SQL Server</dt><dd className="text-title">{data.info.server_version ?? '—'}</dd>
            <dt className="text-muted">Python</dt><dd className="text-title">{data.info.python_version}</dd>
            <dt className="text-muted">Started</dt><dd className="text-title">{formatDateTime(data.info.started_at)}</dd>
            <dt className="text-muted">Uptime</dt><dd className="text-title">{formatUptime(data.info.uptime_seconds)}</dd>
          </dl>
        </Card>
      )}
    </div>
  )
}
