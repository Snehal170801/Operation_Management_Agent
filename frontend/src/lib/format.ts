export function humanize(value?: string | null): string {
  if (!value) return '—'
  return value.replace(/[_.]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

/** The backend stores UTC but sends timestamps without a zone marker. */
export function formatDateTime(value?: string | null): string {
  if (!value) return '—'
  const iso = /Z$|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatAmount(value?: number | null): string {
  if (value == null) return '—'
  return value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** A calendar date (no time), e.g. a delivery due date. */
export function formatDate(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(`${value.slice(0, 10)}T00:00:00`)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

/** A whole-number amount for a headline figure: "42,000", or "1.2M" once it gets big (no ".00" noise). */
export function formatAmountShort(value?: number | null): string {
  if (value == null) return '—'
  if (Math.abs(value) >= 1_000_000) {
    return value.toLocaleString(undefined, { notation: 'compact', maximumFractionDigits: 1 })
  }
  return value.toLocaleString(undefined, { maximumFractionDigits: 0 })
}
