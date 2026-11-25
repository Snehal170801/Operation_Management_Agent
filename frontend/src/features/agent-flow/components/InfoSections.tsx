import { Check, Clock, Info, X, type LucideIcon } from 'lucide-react'
import clsx from 'clsx'
import { formatDate, formatDateTime } from '@/lib/format'
import type { InfoSection } from '../types'

/** The server sends dates as plain text; show them the way the rest of the app does. */
function pretty(value: string | null | undefined): string {
  if (!value) return '—'
  if (/^\d{4}-\d{2}-\d{2}T/.test(value)) return formatDateTime(value)
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return formatDate(value)
  return value
}

const CHECK: Record<string, { Icon: LucideIcon; ring: string }> = {
  pass: { Icon: Check, ring: 'bg-emerald-100 text-emerald-700' },
  fail: { Icon: X, ring: 'bg-red-100 text-red-700' },
  wait: { Icon: Clock, ring: 'bg-amber-100 text-amber-700' },
  info: { Icon: Info, ring: 'bg-slate-100 text-slate-600' },
}

const DOT: Record<string, string> = { info: 'bg-brand', ok: 'bg-[#16A34A]', warn: 'bg-amber-500', bad: 'bg-danger' }

function Heading({ children }: { children: string }) {
  return <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">{children}</h4>
}

function Section({ section }: { section: InfoSection }) {
  switch (section.kind) {
    case 'facts':
      return (
        <section>
          <Heading>{section.title}</Heading>
          <dl className="mt-2 divide-y divide-line rounded-xl border border-line">
            {section.items.map((item) => (
              <div key={item.label} className="flex items-start justify-between gap-6 px-4 py-2.5 text-sm">
                <dt className="shrink-0 text-muted">{item.label}</dt>
                <dd className="min-w-0 break-words text-right font-medium text-title">{pretty(item.value)}</dd>
              </div>
            ))}
          </dl>
        </section>
      )

    case 'text':
      return (
        <section>
          <Heading>{section.title}</Heading>
          <p className="mt-2 whitespace-pre-wrap break-words rounded-xl bg-brand-tint px-4 py-3 text-sm leading-relaxed text-title">{section.body}</p>
        </section>
      )

    case 'table':
      return (
        <section>
          <Heading>{section.title}</Heading>
          <div className="mt-2 overflow-x-auto rounded-xl border border-line">
            <table className="w-full table-auto text-left text-sm">
              <thead className="bg-brand-tint/60 text-xs text-muted">
                <tr>
                  {section.columns.map((c) => (
                    <th key={c} className="px-3 py-2 font-semibold">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {section.rows.map((row, i) => {
                  const chosen = section.highlight === i
                  return (
                    <tr key={i} className={clsx(chosen && 'bg-emerald-50')}>
                      {row.map((cell, j) => (
                        <td key={j} className={clsx('break-words px-3 py-2.5 align-top', j === 0 && 'font-medium text-title', cell.length > 40 && 'min-w-[160px] text-muted')}>
                          {j === 0 && chosen && <Check size={14} className="mr-1.5 inline text-emerald-600" aria-label="Chosen" />}
                          {pretty(cell)}
                        </td>
                      ))}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </section>
      )

    case 'checks':
      return (
        <section>
          <Heading>{section.title}</Heading>
          <ul className="mt-2 divide-y divide-line rounded-xl border border-line">
            {section.items.map((item) => {
              const look = CHECK[item.status ?? 'info'] ?? CHECK.info
              return (
                <li key={item.label} className="flex items-start gap-3 px-4 py-3">
                  <span className={clsx('mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full', look.ring)}>
                    <look.Icon size={12} strokeWidth={3} />
                  </span>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-title">{item.label}</p>
                    {item.detail && <p className="mt-0.5 break-words text-xs text-muted">{item.detail}</p>}
                  </div>
                </li>
              )
            })}
          </ul>
        </section>
      )

    case 'timeline':
      return (
        <section>
          <Heading>{section.title}</Heading>
          <ul className="mt-2 divide-y divide-line rounded-xl border border-line">
            {section.items.map((item, i) => (
              <li key={i} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                <span className={clsx('h-2.5 w-2.5 shrink-0 rounded-full', DOT[item.tone ?? 'info'] ?? DOT.info)} />
                <span className="min-w-0 flex-1 text-title">{item.text}</span>
                <span className="shrink-0 text-xs tabular-nums text-muted">{item.at ? formatDateTime(item.at) : ''}</span>
              </li>
            ))}
          </ul>
        </section>
      )

    default:
      return null
  }
}

/** The full, structured account of what one agent did on this case. */
export function InfoSections({ sections }: { sections: InfoSection[] }) {
  return (
    <>
      {sections.map((section) => (
        <Section key={`${section.kind}:${section.title}`} section={section} />
      ))}
    </>
  )
}
