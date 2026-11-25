import { Boxes, FileText, Handshake, PackageCheck, Receipt, ShieldCheck, Truck, type LucideIcon } from 'lucide-react'
import type { AgentKey, AgentState } from './types'

export const AGENT_ICON: Record<AgentKey, LucideIcon> = {
  purchase: FileText,
  procurement: Boxes,
  vendor: Handshake,
  approval: ShieldCheck,
  po: PackageCheck,
  delivery: Truck,
  invoice: Receipt,
}

interface StateStyle {
  /** Short word shown on the state pill. */
  word: string
  /** The round icon: background / border / icon colour. */
  orb: string
  pill: string
  /** Colour of the dot in the legend. */
  dot: string
}

const BRAND_GRADIENT = 'bg-[linear-gradient(135deg,#c53536_0%,#ea4d4e_100%)]'

export const STATE_STYLE: Record<AgentState, StateStyle> = {
  done: { word: 'Done', orb: 'bg-[#16A34A] text-white', pill: 'bg-[#DCFCE7] text-[#16A34A]', dot: 'bg-[#16A34A]' },
  working: {
    word: 'Working',
    orb: `${BRAND_GRADIENT} text-white shadow-[0_0_0_6px_rgba(234,77,78,0.15)]`,
    pill: 'bg-brand-soft text-brand-ink',
    dot: 'bg-brand',
  },
  waiting: {
    word: 'Waiting',
    orb: 'border-2 border-amber-400 bg-white text-amber-600',
    pill: 'bg-[#FEF3C7] text-[#B45309]',
    dot: 'bg-amber-400',
  },
  needs_person: {
    word: 'Needs a person',
    orb: 'border-2 border-danger bg-danger-soft text-danger shadow-[0_0_0_6px_rgba(197,53,54,0.10)]',
    pill: 'bg-danger-soft text-danger',
    dot: 'bg-danger',
  },
  pending: { word: 'Not started', orb: 'bg-slate-100 text-slate-400', pill: 'bg-slate-100 text-slate-500', dot: 'bg-slate-300' },
  skipped: {
    word: 'Not needed',
    orb: 'border-2 border-dashed border-slate-300 bg-white text-slate-300',
    pill: 'bg-slate-100 text-slate-500',
    dot: 'bg-slate-200',
  },
  stopped: { word: 'Stopped', orb: 'bg-slate-700 text-white', pill: 'bg-slate-200 text-slate-700', dot: 'bg-slate-600' },
  failed: { word: 'Failed', orb: 'bg-danger text-white', pill: 'bg-danger-soft text-danger', dot: 'bg-danger' },
}

/** Order used by the legend. */
export const LEGEND: AgentState[] = ['done', 'working', 'waiting', 'needs_person', 'pending', 'skipped']

/** A connector line leading OUT of an agent: green once that agent has handed its work on. */
export function connectorTone(state: AgentState): string {
  if (state === 'done') return 'bg-[#16A34A]'
  if (state === 'skipped') return 'border-t-2 border-dashed border-slate-200 bg-transparent'
  return 'bg-line'
}

/** How each state looks on the dark stage. */
export const ORB_STYLE: Record<AgentState, string> = {
  done: 'bg-[linear-gradient(135deg,#22c55e,#15803d)] text-white shadow-[0_0_28px_rgba(34,197,94,0.35)]',
  working: 'bg-[linear-gradient(135deg,#ff6b6c,#c53536)] text-white shadow-[0_0_34px_rgba(234,77,78,0.65)]',
  waiting: 'border-2 border-amber-400/80 bg-amber-400/10 text-amber-300 shadow-[0_0_22px_rgba(251,191,36,0.25)]',
  needs_person: 'border-2 border-red-400 bg-red-500/15 text-red-200 shadow-[0_0_26px_rgba(248,113,113,0.4)]',
  pending: 'border border-white/10 bg-white/5 text-white/30',
  skipped: 'border-2 border-dashed border-white/15 bg-transparent text-white/20',
  stopped: 'bg-slate-600 text-white',
  failed: 'bg-red-600 text-white shadow-[0_0_26px_rgba(220,38,38,0.5)]',
}

export const PILL_STYLE: Record<AgentState, string> = {
  done: 'bg-emerald-400/15 text-emerald-300',
  working: 'bg-brand/25 text-rose-100',
  waiting: 'bg-amber-400/15 text-amber-300',
  needs_person: 'bg-red-400/20 text-red-200',
  pending: 'bg-white/10 text-white/50',
  skipped: 'bg-white/5 text-white/40',
  stopped: 'bg-slate-500/30 text-slate-200',
  failed: 'bg-red-500/25 text-red-200',
}

/** Sizes and colour key shared by the one-case stage and the live board. */
export const ORB = 76 // px: the round icon
export const RING = ORB + 16 // the progress ring around it

export const DOT: Record<AgentState, string> = {
  done: 'bg-emerald-400', working: 'bg-brand', waiting: 'bg-amber-400', needs_person: 'bg-red-400',
  pending: 'bg-white/30', skipped: 'bg-white/15', stopped: 'bg-slate-400', failed: 'bg-red-500',
}
