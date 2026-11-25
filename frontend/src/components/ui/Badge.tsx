import clsx from 'clsx'
import { humanize } from '@/lib/format'

const TONES: Record<string, string> = {
  open: 'bg-[#DCFCE7] text-[#16A34A]',
  closed: 'bg-slate-100 text-slate-600',
  rejected: 'bg-danger-soft text-danger',
  pending: 'bg-[#FEF3C7] text-[#B45309]',
  approved: 'bg-[#DCFCE7] text-[#16A34A]',
  auto_approved: 'bg-[#DCFCE7] text-[#16A34A]',
  superseded: 'bg-slate-100 text-slate-600',
  sent: 'bg-[#DCFCE7] text-[#16A34A]',
  replied: 'bg-[#DCFCE7] text-[#16A34A]',
  delivered: 'bg-[#DCFCE7] text-[#16A34A]',
  send_failed: 'bg-danger-soft text-danger',
  matched: 'bg-[#DCFCE7] text-[#16A34A]',
  on_hold: 'bg-[#FEF3C7] text-[#B45309]',
  mismatch: 'bg-danger-soft text-danger',
  completed: 'bg-slate-100 text-slate-600',
  in_stock: 'bg-[#DCFCE7] text-[#16A34A]',
  low: 'bg-[#FEF3C7] text-[#B45309]',
  out_of_stock: 'bg-danger-soft text-danger',
}

export function Badge({ value }: { value: string }) {
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-semibold',
        TONES[value] ?? 'bg-brand-soft text-brand-ink',
      )}
    >
      {humanize(value)}
    </span>
  )
}
