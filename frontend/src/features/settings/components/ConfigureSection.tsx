import { useMemo, useState, type ReactNode } from 'react'
import { BadgeCheck, BellRing, Check, Cpu, Lock, Minus, PackageSearch, PhoneCall, Plus, ReceiptText, RotateCcw, type LucideIcon } from 'lucide-react'
import clsx from 'clsx'
import { Button } from '@/components/ui/Button'
import { QueryState } from '@/components/ui/QueryState'
import { useAuth } from '@/features/auth/AuthContext'
import { useConfig, useResetConfig, useSaveConfig, type ConfigItem } from '../config'

type Draft = Record<string, string | number | boolean>

const show = (v: number | boolean) => (typeof v === 'boolean' ? (v ? 'On' : 'Off') : v.toLocaleString('en-IN'))

// Each group has its own icon and colour, so you can tell them apart at a glance.
const LOOK: Record<string, { Icon: LucideIcon; tile: string; wash: string }> = {
  reminders: { Icon: BellRing, tile: 'bg-amber-100 text-amber-600', wash: 'from-amber-50' },
  approval: { Icon: BadgeCheck, tile: 'bg-emerald-100 text-emerald-600', wash: 'from-emerald-50' },
  invoice: { Icon: ReceiptText, tile: 'bg-sky-100 text-sky-600', wash: 'from-sky-50' },
  requests: { Icon: PackageSearch, tile: 'bg-violet-100 text-violet-600', wash: 'from-violet-50' },
  worker: { Icon: Cpu, tile: 'bg-slate-200 text-slate-600', wash: 'from-slate-100' },
  calls: { Icon: PhoneCall, tile: 'bg-rose-100 text-rose-600', wash: 'from-rose-50' },
  security: { Icon: Lock, tile: 'bg-red-100 text-brand-ink', wash: 'from-red-50' },
}
const lookOf = (key: string) => LOOK[key] ?? LOOK.worker

/** How far the + and - buttons move a value. */
function stepOf(item: ConfigItem): number {
  if (item.unit === '₹') return 1000
  if (item.unit === 'out of 5' || item.unit === '%') return 0.5
  return 1
}

/** A value is fine if it is a number inside the setting's limits (the server checks again). */
function problem(item: ConfigItem, raw: string | number | boolean): string | null {
  if (item.kind === 'bool') return null
  const n = Number(raw)
  if (raw === '' || Number.isNaN(n)) return 'Enter a number.'
  if (item.kind === 'int' && n !== Math.round(n)) return 'Use a whole number.'
  if (n < item.minimum || n > item.maximum) return `Between ${item.minimum.toLocaleString('en-IN')} and ${item.maximum.toLocaleString('en-IN')}.`
  return null
}

function Switch({ on, label, disabled, onChange }: { on: boolean; label: string; disabled: boolean; onChange: (next: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!on)}
      className="inline-flex items-center gap-3 disabled:cursor-not-allowed disabled:opacity-60"
    >
      <span className={clsx('relative h-7 w-12 rounded-full transition-colors', on ? 'bg-[#16A34A]' : 'bg-slate-300')}>
        <span className={clsx('absolute top-1 grid h-5 w-5 place-items-center rounded-full bg-white shadow transition-all', on ? 'left-6' : 'left-1')}>
          {on && <Check size={12} className="text-[#16A34A]" />}
        </span>
      </span>
      <span className={clsx('w-7 text-sm font-semibold', on ? 'text-[#16A34A]' : 'text-muted')}>{on ? 'On' : 'Off'}</span>
    </button>
  )
}

function NumberBox({ item, value, disabled, invalid, onChange }: { item: ConfigItem; value: string | number | boolean; disabled: boolean; invalid: boolean; onChange: (v: string) => void }) {
  const nudge = (direction: 1 | -1) => {
    const next = Math.min(item.maximum, Math.max(item.minimum, Math.round(((Number(value) || 0) + direction * stepOf(item)) * 100) / 100))
    onChange(String(next))
  }
  const button = 'grid h-full w-9 place-items-center text-muted transition-colors hover:bg-brand-tint hover:text-brand-ink disabled:pointer-events-none disabled:opacity-40'
  return (
    <div
      className={clsx(
        'flex h-11 items-center overflow-hidden rounded-xl border bg-white shadow-[0_1px_2px_rgba(15,23,42,0.05)] focus-within:ring-4',
        invalid ? 'border-danger focus-within:ring-danger/15' : 'border-line focus-within:border-brand focus-within:ring-brand/15',
      )}
    >
      <button type="button" aria-label={`Decrease ${item.label}`} disabled={disabled} onClick={() => nudge(-1)} className={button}>
        <Minus size={15} />
      </button>
      <input
        type="number"
        inputMode="decimal"
        aria-label={item.label}
        aria-invalid={invalid}
        min={item.minimum}
        max={item.maximum}
        step={item.kind === 'int' ? 1 : 'any'}
        disabled={disabled}
        value={String(value)}
        onChange={(e) => onChange(e.target.value)}
        className="h-full w-16 appearance-none bg-transparent text-center text-base font-semibold text-title focus:outline-none disabled:text-muted [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
      />
      <button type="button" aria-label={`Increase ${item.label}`} disabled={disabled} onClick={() => nudge(1)} className={button}>
        <Plus size={15} />
      </button>
    </div>
  )
}

/** The settings the agents follow, one group at a time. Changes apply the moment they are saved; no restart. */
export function ConfigureSection() {
  const { can } = useAuth()
  const editable = can('system:write')
  const { data, isLoading, error } = useConfig()
  const save = useSaveConfig()
  const reset = useResetConfig()
  const [active, setActive] = useState<string>()
  // What the person has typed but not yet saved, by setting key.
  const [draft, setDraft] = useState<Draft>({})
  const [saved, setSaved] = useState(false)

  const groups = data?.groups ?? []
  const items = useMemo(() => groups.flatMap((g) => g.items), [groups])
  const byKey = useMemo(() => new Map(items.map((i) => [i.key, i])), [items])
  const dirty = useMemo(() => items.filter((i) => i.key in draft && String(draft[i.key]) !== String(i.value)), [items, draft])

  const valueOf = (i: ConfigItem) => (i.key in draft ? draft[i.key] : i.value)
  const set = (key: string, v: string | number | boolean) => {
    setSaved(false)
    save.reset()
    reset.reset()
    setDraft((d) => ({ ...d, [key]: v }))
  }
  const clear = () => setDraft({})

  // The calling window is one idea, so it is one row: "from 9 to 19". It must start before it ends.
  const startItem = byKey.get('CALL_HOURS_START')
  const endItem = byKey.get('CALL_HOURS_END')
  const hoursProblem = (() => {
    if (!startItem || !endItem) return null
    const a = problem(startItem, valueOf(startItem))
    const b = problem(endItem, valueOf(endItem))
    if (a || b) return a ?? b
    return Number(valueOf(startItem)) >= Number(valueOf(endItem)) ? "The 'from' hour must be earlier than the 'until' hour." : null
  })()
  const invalid = dirty.some((i) => problem(i, draft[i.key])) || (!!hoursProblem && dirty.some((i) => i.key.startsWith('CALL_HOURS')))

  const onSave = () =>
    save.mutate(Object.fromEntries(dirty.map((i) => [i.key, draft[i.key]])), {
      onSuccess: () => {
        clear()
        setSaved(true)
      },
    })
  const onReset = (keys: string[] | null) =>
    reset.mutate(keys, {
      onSuccess: () => {
        clear()
        setSaved(true)
      },
    })

  const changedCount = items.filter((i) => i.changed).length
  const failure = save.error?.message ?? reset.error?.message
  const group = groups.find((g) => g.key === active) ?? groups[0]
  const callSwitch = byKey.get('CALL_AFTER_EMAIL')
  const callsOff = !!callSwitch && !valueOf(callSwitch)

  /** "Back to 24" shown only when a value differs from the standard, so unchanged rows stay quiet. */
  const resetLink = (item: ConfigItem, keys: string[] = [item.key]) => {
    const differs = keys.some((k) => String(valueOf(byKey.get(k)!)) !== String(byKey.get(k)!.default))
    if (!editable || !differs) return null
    const standard = keys.map((k) => show(byKey.get(k)!.default)).join(' to ')
    return (
      <button
        type="button"
        onClick={() => keys.forEach((k) => set(k, byKey.get(k)!.default))}
        className="inline-flex items-center gap-1 text-xs font-medium text-brand-ink hover:underline"
      >
        <RotateCcw size={11} /> Back to {standard}
      </button>
    )
  }

  const row = (key: string, label: string, help: string, control: ReactNode, note: ReactNode, opts: { dim?: boolean; changed?: boolean } = {}) => (
    <li
      key={key}
      className={clsx(
        '-mx-5 flex flex-col gap-3 border-l-4 px-5 py-5 transition-colors hover:bg-slate-50/70 sm:-mx-7 sm:flex-row sm:items-center sm:justify-between sm:gap-8 sm:px-7',
        opts.changed ? 'border-brand bg-brand-tint/40' : 'border-transparent',
        opts.dim && 'opacity-50',
      )}
    >
      <div className="min-w-0 sm:max-w-[56%]">
        <p className="text-sm font-semibold text-title">{label}</p>
        {help && <p className="mt-1 text-sm leading-snug text-muted">{help}</p>}
      </div>
      <div className="flex shrink-0 flex-col gap-1.5 sm:items-end">
        {control}
        {note}
      </div>
    </li>
  )

  const edited = (i: ConfigItem) => i.changed || dirty.includes(i)

  return (
    <QueryState variant="detail" rows={4} isLoading={isLoading} error={error} isEmpty={!data}>
      <div className="flex flex-col gap-5 pb-28">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-title">Configure</h2>
            <p className="mt-0.5 text-sm text-muted">How often the agents remind people, and the limits they stay within. Changes apply as soon as you save.</p>
          </div>
          {editable && changedCount > 0 && (
            <Button variant="secondary" loading={reset.isPending} onClick={() => onReset(null)}>
              <RotateCcw size={15} /> Reset all to standard
            </Button>
          )}
        </div>
        {!editable && <p className="text-sm text-muted">You can see these settings, but only an administrator can change them.</p>}

        <div className="flex flex-col gap-5">
          <nav aria-label="Setting groups" className="scrollbar-hide -mx-1 flex gap-2.5 overflow-x-auto px-1 py-1 xl:mx-0 xl:grid xl:grid-cols-7 xl:overflow-visible xl:px-0">
            {groups.map((g) => {
              const { Icon, tile } = lookOf(g.key)
              const here = g.key === group?.key
              const edits = g.items.filter(edited).length
              return (
                <button
                  key={g.key}
                  type="button"
                  onClick={() => setActive(g.key)}
                  aria-current={here ? 'true' : undefined}
                  className={clsx(
                    'relative flex w-36 shrink-0 flex-col items-center gap-2 rounded-2xl px-3 py-3.5 text-center transition-all xl:w-auto',
                    here ? 'bg-white shadow-md shadow-slate-200/70 ring-2 ring-brand/40' : 'bg-white ring-1 ring-line hover:-translate-y-0.5 hover:shadow-sm motion-reduce:hover:translate-y-0',
                  )}
                >
                  <span className={clsx('grid h-10 w-10 place-items-center rounded-xl', tile)}>
                    <Icon size={19} />
                  </span>
                  <span className="min-w-0">
                    <span className={clsx('block text-sm font-semibold leading-tight', here ? 'text-title' : 'text-muted')}>{g.label}</span>
                    <span className="mt-0.5 block text-xs text-muted">
                      {g.items.length} setting{g.items.length === 1 ? '' : 's'}
                    </span>
                  </span>
                  {edits > 0 && <span className="absolute right-2.5 top-2.5 h-2 w-2 rounded-full bg-brand" title={`${edits} changed`} />}
                </button>
              )
            })}
          </nav>

          {group && (
            <section aria-label={group.label} className="overflow-hidden rounded-2xl border border-card-border bg-white px-5 pb-2 shadow-[0_1px_2px_rgba(15,23,42,0.04)] sm:px-7">
              <header className={clsx('-mx-5 flex items-center gap-4 border-b border-line bg-linear-to-r to-white px-5 py-5 sm:-mx-7 sm:px-7', lookOf(group.key).wash)}>
                <span className={clsx('grid h-12 w-12 shrink-0 place-items-center rounded-2xl', lookOf(group.key).tile)}>
                  {(() => {
                    const { Icon } = lookOf(group.key)
                    return <Icon size={22} />
                  })()}
                </span>
                <div className="min-w-0">
                  <h3 className="text-lg font-semibold text-title">{group.label}</h3>
                  <p className="mt-0.5 text-sm text-muted">{group.help}</p>
                </div>
              </header>
              <ul className="divide-y divide-line">
                {group.items.map((item) => {
                  if (item.key === 'CALL_HOURS_END' && startItem) return null // shown with the start, below
                  const v = valueOf(item)
                  const dim = callsOff && item.key.startsWith('CALL_') && item.key !== 'CALL_AFTER_EMAIL'

                  if (item.key === 'CALL_HOURS_START' && endItem) {
                    return row(
                      'hours',
                      'Calling hours',
                      'India time, 24-hour clock. A call that would fall outside these hours is skipped.',
                      <div className="flex items-center gap-2.5 text-sm text-muted">
                        from
                        <NumberBox item={item} value={v} disabled={!editable} invalid={!!problem(item, v) || !!hoursProblem} onChange={(x) => set(item.key, x)} />
                        to
                        <NumberBox item={endItem} value={valueOf(endItem)} disabled={!editable} invalid={!!problem(endItem, valueOf(endItem)) || !!hoursProblem} onChange={(x) => set(endItem.key, x)} />
                      </div>,
                      hoursProblem ? <p className="text-xs text-danger">{hoursProblem}</p> : resetLink(item, [item.key, endItem.key]),
                      { dim, changed: edited(item) || edited(endItem) },
                    )
                  }

                  const bad = problem(item, v)
                  return row(
                    item.key,
                    item.label,
                    item.help,
                    item.kind === 'bool' ? (
                      <Switch on={Boolean(v)} label={item.label} disabled={!editable} onChange={(x) => set(item.key, x)} />
                    ) : (
                      <div className="flex items-center gap-2.5">
                        <NumberBox item={item} value={v} disabled={!editable} invalid={!!bad} onChange={(x) => set(item.key, x)} />
                        {item.unit && <span className="w-14 text-sm text-muted">{item.unit}</span>}
                      </div>
                    ),
                    bad ? <p className="text-xs text-danger">{bad}</p> : resetLink(item),
                    { dim, changed: edited(item) },
                  )
                })}
              </ul>
            </section>
          )}
        </div>

        {editable && (dirty.length > 0 || saved || failure) && (
          <div className="fixed inset-x-0 bottom-0 z-20 flex justify-center px-4 pb-4">
            <div className={clsx('flex w-full max-w-3xl flex-wrap items-center justify-between gap-3 rounded-2xl border bg-white px-5 py-3 shadow-xl shadow-slate-300/50', failure ? 'border-danger/40' : 'border-card-border')}>
              <p className={clsx('flex items-center gap-2 text-sm font-medium', failure ? 'text-danger' : 'text-title')}>
                {!failure && dirty.length === 0 && <Check size={16} className="text-[#16A34A]" />}
                {failure ?? (dirty.length > 0 ? `${dirty.length} change${dirty.length > 1 ? 's' : ''} not saved yet` : 'Saved. The agents are using the new values now.')}
              </p>
              {dirty.length > 0 && (
                <div className="flex gap-3">
                  <Button variant="secondary" onClick={clear}>
                    Discard
                  </Button>
                  <Button loading={save.isPending} disabled={invalid} onClick={onSave}>
                    Save changes
                  </Button>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </QueryState>
  )
}
