import type { ReactNode } from 'react'
import clsx from 'clsx'

interface CardProps {
  title?: string
  /** Small text or a control shown at the right of the header. */
  action?: ReactNode
  children: ReactNode
  className?: string
  bodyClassName?: string
}

/** Rounded white panel, hairline border, header strip separated from the body by a divider. */
export function Card({ title, action, children, className, bodyClassName = 'p-5' }: CardProps) {
  return (
    <section
      className={clsx(
        'flex min-h-0 flex-col overflow-hidden rounded-2xl border border-card-border bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)]',
        className,
      )}
    >
      {title && (
        <div className="flex shrink-0 items-center justify-between gap-3 border-b border-line px-5 py-3">
          <h2 className="text-sm font-semibold text-title">{title}</h2>
          {action != null && <span className="text-xs text-muted">{action}</span>}
        </div>
      )}
      <div className={clsx('min-h-0 flex-1', bodyClassName)}>{children}</div>
    </section>
  )
}
