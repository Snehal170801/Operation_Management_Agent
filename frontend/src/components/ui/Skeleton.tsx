import type { CSSProperties } from 'react'
import clsx from 'clsx'

/** One shimmering placeholder block. Decorative: hidden from screen readers (the wrappers announce "Loading"). */
export function Skeleton({ className, style }: { className?: string; style?: CSSProperties }) {
  return <div aria-hidden="true" className={clsx('animate-shimmer rounded-md', className)} style={style} />
}

/** Wrapper that tells assistive tech something is loading, without announcing every bar. */
function Busy({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <div role="status" aria-busy="true" aria-live="polite" className={className}>
      <span className="sr-only">Loading…</span>
      {children}
    </div>
  )
}

// A varied width per cell so the placeholder looks like real text, not a grid of identical bars.
const WIDTHS = ['72%', '58%', '84%', '46%', '66%', '78%', '52%']
const widthFor = (row: number, col: number) => WIDTHS[(row * 3 + col * 2) % WIDTHS.length]

/** Same geometry as <Table>: tinted header strip, 56px rows with hairline borders. */
export function TableSkeleton({ columns = 5, rows = 8 }: { columns?: number; rows?: number }) {
  return (
    <Busy className="min-h-0 flex-1 overflow-hidden">
      <div className="hidden h-[52px] items-center gap-6 bg-brand-tint px-6 md:flex">
        {Array.from({ length: columns }).map((_, c) => (
          <Skeleton key={c} className="h-3.5" style={{ width: c === 0 ? 48 : `${60 + ((c * 17) % 40)}px`, flex: c === 0 ? 'none' : undefined }} />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex min-h-14 flex-col gap-2.5 border-t border-line px-4 py-3.5 md:h-14 md:flex-row md:items-center md:gap-6 md:px-6 md:py-0" style={{ opacity: 1 - r * 0.07 }}>
          {Array.from({ length: columns }).map((_, c) => (
            <div key={c} className={c > 2 ? 'hidden min-w-0 md:block' : 'min-w-0'} style={{ flex: c === 0 ? undefined : 1 }}>
              {/* The second-to-last column is usually a status badge: a rounded pill. */}
              {c === columns - 2 && columns > 3 ? (
                <Skeleton className="h-6 w-20 rounded-full" />
              ) : (
                <Skeleton className="h-3.5" style={{ width: c === 0 ? '100%' : widthFor(r, c) }} />
              )}
            </div>
          ))}
        </div>
      ))}
    </Busy>
  )
}

/** Rows with an icon circle, two text lines and a trailing pill (activity lists, timelines, requests). */
export function ListSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <Busy className="divide-y divide-line">
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex items-center gap-3 px-5 py-3.5" style={{ opacity: 1 - r * 0.1 }}>
          <Skeleton className="h-9 w-9 shrink-0 rounded-full" />
          <div className="min-w-0 flex-1 space-y-2">
            <Skeleton className="h-3.5" style={{ width: widthFor(r, 1) }} />
            <Skeleton className="h-3" style={{ width: widthFor(r, 3) }} />
          </div>
          <Skeleton className="h-6 w-16 rounded-full" />
        </div>
      ))}
    </Busy>
  )
}

/** Label / value pairs, like the "Case" and "Purchase order" cards. */
export function DetailSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <Busy className="grid grid-cols-[7rem_1fr] items-center gap-y-4 p-5">
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="contents">
          <Skeleton className="h-3 w-16" />
          <Skeleton className="h-3.5" style={{ width: widthFor(r, 2) }} />
        </div>
      ))}
    </Busy>
  )
}

/** Plain text lines: the general-purpose fallback. */
export function LinesSkeleton({ lines = 5 }: { lines?: number }) {
  return (
    <Busy className="space-y-3 p-5">
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} className="h-4" style={{ width: `${92 - i * 9}%` }} />
      ))}
    </Busy>
  )
}

/** A row of small bordered cards (system-health checks). */
export function CardsSkeleton({ cards = 3 }: { cards?: number }) {
  return (
    <Busy className="grid grid-cols-1 gap-3 p-5 md:grid-cols-3">
      {Array.from({ length: cards }).map((_, i) => (
        <div key={i} className="flex items-start gap-3 rounded-xl border border-line p-4">
          <Skeleton className="h-10 w-10 shrink-0 rounded-xl" />
          <div className="flex-1 space-y-2 pt-1">
            <Skeleton className="h-3.5 w-24" />
            <Skeleton className="h-3 w-32" />
          </div>
        </div>
      ))}
    </Busy>
  )
}

/** Same box as <StatTile>, so the dashboard doesn't reflow when numbers arrive. */
export function StatTileSkeleton() {
  return (
    <div
      role="status"
      aria-busy="true"
      className="flex h-[124px] items-start justify-between gap-3 rounded-2xl border border-card-border bg-white p-5"
    >
      <span className="sr-only">Loading…</span>
      <div className="space-y-3">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-8 w-16" />
        <Skeleton className="h-3 w-28" />
      </div>
      <Skeleton className="h-11 w-11 shrink-0 rounded-xl" />
    </div>
  )
}

/** Two panes: a list of selectable cards beside a form-like editor (Roles & Permissions). */
export function MasterDetailSkeleton() {
  return (
    <Busy className="grid grid-cols-1 gap-4 lg:grid-cols-[300px_1fr]">
      <div className="flex flex-col gap-2 self-start">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="rounded-2xl border border-card-border bg-white p-4">
            <Skeleton className="mb-2.5 h-4 w-32" />
            <Skeleton className="h-3 w-24" />
          </div>
        ))}
      </div>
      <div className="space-y-4">
        <div className="rounded-2xl border border-card-border bg-white p-5">
          <Skeleton className="mb-4 h-4 w-28" />
          <Skeleton className="mb-3 h-11 max-w-lg" />
          <Skeleton className="h-16 max-w-lg" />
        </div>
        <div className="rounded-2xl border border-card-border bg-white p-5">
          <Skeleton className="mb-4 h-4 w-28" />
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="mb-3 h-14" />
          ))}
        </div>
      </div>
    </Busy>
  )
}

/** The whole signed-in frame (sidebar + top bar + content) shown while the session is being restored. */
export function AppShellSkeleton() {
  return (
    <Busy className="flex h-dvh w-full overflow-hidden bg-page">
      <aside className="hidden w-[260px] shrink-0 flex-col border-r border-line bg-white lg:flex">
        <div className="flex h-16 items-center gap-2.5 border-b border-line px-5">
          <Skeleton className="h-9 w-9 rounded-xl" />
          <Skeleton className="h-4 w-32" />
        </div>
        <div className="space-y-2 p-3 pt-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-11 rounded-lg" style={{ opacity: 1 - i * 0.07 }} />
          ))}
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-16 items-center justify-between border-b border-line bg-white px-3 sm:px-6">
          <Skeleton className="h-10 w-10 rounded-lg" />
          <div className="flex items-center gap-4">
            <Skeleton className="h-10 w-10 rounded-full" />
            <Skeleton className="h-10 w-10 rounded-full" />
          </div>
        </header>
        <main className="flex-1 space-y-4 p-4 sm:p-6">
          <Skeleton className="h-8 w-48" />
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <StatTileSkeleton key={i} />
            ))}
          </div>
          <div className="overflow-hidden rounded-2xl border border-card-border bg-white">
            <TableSkeleton columns={5} rows={6} />
          </div>
        </main>
      </div>
    </Busy>
  )
}
