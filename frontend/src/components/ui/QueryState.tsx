import type { ReactNode } from 'react'
import { CardsSkeleton, DetailSkeleton, LinesSkeleton, ListSkeleton, TableSkeleton } from './Skeleton'

export type SkeletonVariant = 'table' | 'list' | 'detail' | 'lines' | 'cards'

interface Props {
  isLoading: boolean
  error: Error | null
  isEmpty?: boolean
  emptyMessage?: string
  /** Which placeholder to show while loading: pick the one shaped like the real content. */
  variant?: SkeletonVariant
  /** Table placeholder only: number of columns. */
  columns?: number
  /** Number of placeholder rows / lines. */
  rows?: number
  /** Full override (for layouts the presets don't cover). */
  skeleton?: ReactNode
  children: ReactNode
}

function Placeholder({ variant, columns, rows }: Pick<Props, 'variant' | 'columns' | 'rows'>) {
  switch (variant) {
    case 'table':
      return <TableSkeleton columns={columns} rows={rows} />
    case 'list':
      return <ListSkeleton rows={rows} />
    case 'detail':
      return <DetailSkeleton rows={rows} />
    case 'cards':
      return <CardsSkeleton cards={rows} />
    default:
      return <LinesSkeleton lines={rows} />
  }
}

/** Renders loading (skeleton) / error / empty states so pages only handle the happy path. */
export function QueryState({
  isLoading,
  error,
  isEmpty,
  emptyMessage = 'Nothing here yet.',
  variant = 'lines',
  columns,
  rows,
  skeleton,
  children,
}: Props) {
  if (isLoading) return <>{skeleton ?? <Placeholder variant={variant} columns={columns} rows={rows} />}</>
  if (error) return <p className="px-5 py-10 text-sm text-danger">{error.message}</p>
  if (isEmpty) return <p className="px-5 py-10 text-sm text-muted">{emptyMessage}</p>
  return <>{children}</>
}
