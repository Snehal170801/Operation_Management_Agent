import { Hourglass } from 'lucide-react'
import clsx from 'clsx'
import { parseUtc } from '@/lib/time'

/** "3 h 20 min", "42 min", "1 d 3 h", "under a minute": how long is left, in words. */
export function formatLeft(ms: number): string {
  const minutes = Math.ceil(ms / 60_000)
  if (minutes <= 1) return 'under a minute'
  if (minutes < 60) return `${minutes} min`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} h${minutes % 60 ? ` ${minutes % 60} min` : ''}`
  return `${Math.floor(hours / 24)} d${hours % 24 ? ` ${hours % 24} h` : ''}`
}

type Tone = 'calm' | 'soon' | 'urgent' | 'over'

const TONE: Record<Tone, { text: string; bar: string; track: string }> = {
  calm: { text: 'text-emerald-700', bar: 'bg-emerald-500', track: 'bg-emerald-100' },
  soon: { text: 'text-amber-700', bar: 'bg-amber-500', track: 'bg-amber-100' },
  urgent: { text: 'text-danger', bar: 'bg-danger', track: 'bg-danger-soft' },
  over: { text: 'text-danger', bar: 'bg-danger', track: 'bg-danger-soft' },
}

/** The colour follows how much of the time allowed is left: green above half, amber below half, red in the last fifth. */
export function toneFor(fractionLeft: number): Tone {
  if (fractionLeft <= 0) return 'over'
  if (fractionLeft < 0.2) return 'urgent'
  if (fractionLeft < 0.5) return 'soon'
  return 'calm'
}

/** A slim countdown to the moment the admin is told that nobody has acted, with a bar that empties as it nears. */
export function Countdown({ since, escalatesAt, now }: { since: string; escalatesAt: string; now: number }) {
  const start = parseUtc(since)
  const end = parseUtc(escalatesAt)
  const total = Math.max(1, end - start)
  const left = end - now
  const fraction = Math.max(0, Math.min(1, left / total))
  const tone = TONE[toneFor(left / total)]

  return (
    <div className="mt-2 max-w-xs" role="timer" aria-label={left > 0 ? `Escalates in ${formatLeft(left)}` : 'Escalated to the admin'}>
      <p className={clsx('flex items-center gap-1.5 text-xs font-semibold tabular-nums', tone.text)}>
        <Hourglass size={13} aria-hidden />
        {left > 0 ? `Escalates in ${formatLeft(left)}` : 'Escalated to the admin'}
      </p>
      <div className={clsx('mt-1 h-1 overflow-hidden rounded-full', tone.track)}>
        <div className={clsx('h-full rounded-full transition-[width] duration-1000 ease-linear motion-reduce:transition-none', tone.bar)} style={{ width: `${fraction * 100}%` }} />
      </div>
    </div>
  )
}
