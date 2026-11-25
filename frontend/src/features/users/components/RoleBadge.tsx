import clsx from 'clsx'
import { humanize } from '@/lib/format'

const TONES: Record<string, string> = {
  admin: 'bg-brand-soft text-brand-ink',
  manager: 'bg-[#DBEAFE] text-[#1D4ED8]',
  viewer: 'bg-slate-100 text-slate-600',
  user: 'bg-[#DCFCE7] text-[#16A34A]',
}

export function RoleBadge({ role }: { role: string }) {
  return (
    <span className={clsx('inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-semibold', TONES[role] ?? TONES.viewer)}>
      {humanize(role)}
    </span>
  )
}
