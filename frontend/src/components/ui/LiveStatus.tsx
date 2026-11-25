import clsx from 'clsx'
import { timeAgo } from '@/lib/time'

interface LiveStatusProps {
  /** When the data on screen was last received (ms since epoch). */
  updatedAt: number
  /** A refresh is in flight right now. */
  fetching: boolean
  /** The last refresh failed but earlier data is still shown. */
  failed: boolean
  /** The current time, from useNow(), so "3s ago" keeps counting. */
  now: number
  /** For use on a dark background. */
  dark?: boolean
  /** Show just "Live", without when it was last updated (it is still amber, with the reason, if the connection is lost). */
  minimal?: boolean
}

/** A pulsing dot and "Live · updated 3s ago". Turns amber, and says so, if the connection is lost. */
export function LiveStatus({ updatedAt, fetching, failed, now, dark, minimal }: LiveStatusProps) {
  return (
    <div className={clsx('flex items-center gap-2 text-xs', dark ? 'text-white/60' : 'text-muted')} role="status" aria-live="polite">
      <span className="relative flex h-2.5 w-2.5">
        {!failed && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#16A34A] opacity-60 motion-reduce:animate-none" />}
        <span className={clsx('relative inline-flex h-2.5 w-2.5 rounded-full', failed ? 'bg-amber-500' : 'bg-[#16A34A]')} />
      </span>
      {failed ? (
        <span className={clsx('font-medium', dark ? 'text-amber-300' : 'text-amber-700')}>Connection lost. Showing the last update, {timeAgo(updatedAt, now)}.</span>
      ) : (
        <span>
          <b className={dark ? 'text-white' : 'text-title'}>Live</b>
          {!minimal && updatedAt ? ` · updated ${timeAgo(updatedAt, now)}` : ''}
          {!minimal && fetching && updatedAt ? ' · refreshing…' : ''}
        </span>
      )}
    </div>
  )
}
