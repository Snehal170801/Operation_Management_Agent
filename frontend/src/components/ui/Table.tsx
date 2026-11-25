import { Children, cloneElement, createContext, isValidElement, useContext, type ReactElement, type ReactNode } from 'react'
import clsx from 'clsx'

/**
 * Table styled like the reference: tinted sticky header, 56px rows, hairline row borders.
 *
 * Below a breakpoint the table "stacks": the header row disappears and every row becomes a card whose
 * cells carry their column name as a label, so nothing needs sideways scrolling on a phone.
 * Wide tables (many columns) stack earlier: pass `stackBelow="xl"`.
 */
type Breakpoint = 'md' | 'xl'

// Tailwind only generates classes it can see written out in full, so each breakpoint spells them out.
const STACK: Record<Breakpoint, Record<'table' | 'head' | 'body' | 'row' | 'cell' | 'hideCell' | 'label' | 'value', string>> = {
  md: {
    table: 'md:min-w-[640px] max-md:block',
    head: 'max-md:hidden',
    body: 'max-md:block max-md:space-y-3 max-md:p-3',
    row: 'max-md:block max-md:h-auto max-md:rounded-xl max-md:border max-md:border-line max-md:bg-white max-md:px-4 max-md:py-1.5',
    cell: 'max-md:flex max-md:items-center max-md:justify-between max-md:gap-4 max-md:border-0 max-md:px-0 max-md:py-2 max-md:pl-0',
    hideCell: 'max-md:hidden',
    label: 'md:hidden',
    value: 'contents max-md:block max-md:min-w-0 max-md:text-right',
  },
  xl: {
    table: 'xl:min-w-[640px] max-xl:block',
    head: 'max-xl:hidden',
    body: 'max-xl:block max-xl:space-y-3 max-xl:p-3',
    row: 'max-xl:block max-xl:h-auto max-xl:rounded-xl max-xl:border max-xl:border-line max-xl:bg-white max-xl:px-4 max-xl:py-1.5',
    cell: 'max-xl:flex max-xl:items-center max-xl:justify-between max-xl:gap-4 max-xl:border-0 max-xl:px-0 max-xl:py-2 max-xl:pl-0',
    hideCell: 'max-xl:hidden',
    label: 'xl:hidden',
    value: 'contents max-xl:block max-xl:min-w-0 max-xl:text-right',
  },
}

const TableContext = createContext<{ headers: string[]; stack: (typeof STACK)['md'] }>({ headers: [], stack: STACK.md })

export function Table({
  headers,
  children,
  stackBelow = 'md',
}: { headers: string[]; children: ReactNode; stackBelow?: Breakpoint }) {
  const stack = STACK[stackBelow]
  return (
    <TableContext.Provider value={{ headers, stack }}>
      <div className="min-h-0 flex-1 overflow-auto">
        <table className={clsx('w-full border-separate border-spacing-0 text-left', stack.table)}>
          <thead className={clsx('sticky top-0 z-[1] bg-brand-tint', stack.head)}>
            <tr className="h-[52px]">
              {headers.map((h, i) => (
                <th key={`${h}-${i}`} className={clsx('px-2 text-sm font-semibold text-title', i === 0 && 'pl-6')}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className={stack.body}>{children}</tbody>
        </table>
      </div>
    </TableContext.Provider>
  )
}

interface TdProps {
  children: ReactNode
  first?: boolean
  className?: string
  /** Set automatically from the table's headers; shown only in the stacked (card) layout. */
  label?: string
}

export function Tr({ children, onClick }: { children: ReactNode; onClick?: () => void }) {
  const { headers, stack } = useContext(TableContext)

  // Hand each cell its column name by position, so pages keep writing plain <Td>s.
  let column = 0
  const cells = Children.map(children, (child) => {
    if (!isValidElement(child) || child.type !== Td) return child
    return cloneElement(child as ReactElement<TdProps>, { label: headers[column++] })
  })

  return (
    <tr
      onClick={onClick}
      className={clsx('h-14 border-t border-line transition-colors hover:bg-brand-tint/60', stack.row, onClick && 'cursor-pointer')}
    >
      {cells}
    </tr>
  )
}

export function Td({ children, first, className, label }: TdProps) {
  const { stack } = useContext(TableContext)
  return (
    <td
      className={clsx(
        'border-t border-line px-2 text-sm text-title',
        first && 'pl-6',
        stack.cell,
        // A row number means nothing on a card.
        label === 'Sr.No.' && stack.hideCell,
        className,
      )}
    >
      {label && <span className={clsx('shrink-0 text-xs font-medium text-muted', stack.label)}>{label}</span>}
      <span className={stack.value}>{children}</span>
    </td>
  )
}
