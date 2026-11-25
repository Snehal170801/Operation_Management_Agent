import { Check, Circle, Loader2, Minus, X } from 'lucide-react'
import clsx from 'clsx'
import { FLOW_STEPS, type StepState } from '@/lib/caseFlow'

const ICON: Record<StepState, { Icon: typeof Check; ring: string }> = {
  done: { Icon: Check, ring: 'bg-[#16A34A] text-white' },
  current: { Icon: Loader2, ring: 'bg-brand text-white' },
  pending: { Icon: Circle, ring: 'bg-slate-100 text-slate-400' },
  skipped: { Icon: Minus, ring: 'bg-slate-100 text-slate-400' },
  failed: { Icon: X, ring: 'bg-danger text-white' },
}

/** Vertical stepper of what the agents are doing, in plain words. */
export function FlowTracker({ states }: { states: StepState[] }) {
  return (
    <ol className="flex flex-col">
      {FLOW_STEPS.map((step, i) => {
        const state = states[i] ?? 'pending'
        const { Icon, ring } = ICON[state]
        const last = i === FLOW_STEPS.length - 1
        return (
          <li key={step.key} className="flex gap-3">
            <div className="flex flex-col items-center">
              <span className={clsx('flex h-7 w-7 shrink-0 items-center justify-center rounded-full', ring)}>
                <Icon size={15} strokeWidth={2.6} className={state === 'current' ? 'animate-spin' : undefined} />
              </span>
              {!last && <span className={clsx('my-1 w-0.5 flex-1', state === 'done' ? 'bg-[#16A34A]' : 'bg-line')} />}
            </div>
            <div className={clsx('pb-5', last && 'pb-0')}>
              <div
                className={clsx(
                  'text-sm font-semibold',
                  state === 'pending' || state === 'skipped' ? 'text-muted' : 'text-title',
                )}
              >
                {step.label}
              </div>
              {(state === 'current' || state === 'failed') && <div className="text-xs text-muted">{step.hint}</div>}
              {state === 'skipped' && <div className="text-xs text-muted">Not needed</div>}
            </div>
          </li>
        )
      })}
    </ol>
  )
}
