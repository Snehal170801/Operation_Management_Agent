import type { CSSProperties, FormEvent, ReactNode } from 'react'
import {
  CheckCircle2,
  ClipboardList,
  FileText,
  Lock,
  Mail,
  ShieldCheck,
  Sparkles,
  Truck,
  Workflow,
  type LucideIcon,
} from 'lucide-react'

/** Light, roomy text field (icon on the left, optional control on the right). Wrap in `auth-field` so the icon lights up on focus. */
export const authInputCls =
  'login-input w-full h-14 rounded-2xl border-2 border-transparent bg-slate-100/80 pl-[3.75rem] pr-12 text-[15px] text-title placeholder:text-muted/70 transition-all hover:bg-slate-100 focus:border-brand focus:bg-white focus:outline-none focus:ring-4 focus:ring-brand/15 focus:shadow-[0_8px_22px_-8px_rgba(234,77,78,0.55)]'

export const authIconCls = 'pointer-events-none absolute left-2.5 top-1/2 box-content -translate-y-1/2 rounded-xl bg-brand-tint p-2.5 text-brand-ink transition-colors'

export const authButtonCls =
  'group auth-btn-shine mt-2 flex h-14 items-center justify-center gap-2.5 rounded-2xl bg-[linear-gradient(135deg,#c53536_0%,#ea4d4e_55%,#ff6b6c_100%)] text-base font-semibold text-white shadow-[0_10px_24px_-10px_rgba(197,53,54,0.7)] transition-all hover:-translate-y-0.5 hover:shadow-[0_16px_30px_-10px_rgba(197,53,54,0.75)] active:translate-y-0 disabled:translate-y-0 disabled:cursor-not-allowed disabled:opacity-60 disabled:shadow-none'

export const authLinkCls = 'text-sm font-medium text-brand-ink underline-offset-4 hover:underline'

export const authErrorCls = 'rounded-xl border border-danger/20 bg-danger-soft px-4 py-2.5 text-center text-[13px] font-medium text-danger'
export const authNoticeCls = 'flex items-center gap-2 rounded-xl border border-[#16A34A]/20 bg-[#DCFCE7] px-4 py-2.5 text-[13px] font-medium text-[#15803D]'

/** Staggered entrance: `style={delay(200)}` on an `auth-rise` / `auth-pop` element. */
const delay = (ms: number) => ({ '--d': `${ms}ms` }) as CSSProperties

const FLOW: { Icon: LucideIcon; title: string; text: string }[] = [
  { Icon: ClipboardList, title: 'Request', text: 'Someone asks for what they need, in plain words.' },
  { Icon: Mail, title: 'Quotes', text: 'Suppliers are asked and chased automatically.' },
  { Icon: ShieldCheck, title: 'Approval', text: 'A person is only pulled in when it matters.' },
  { Icon: FileText, title: 'Purchase order', text: 'Issued and sent to the chosen supplier.' },
  { Icon: Truck, title: 'Delivery & invoice', text: 'Tracked, received and matched to the order.' },
]

function Brand({ dark }: { dark?: boolean }) {
  return (
    <div className="flex items-center gap-3">
      <span
        className={
          dark
            ? 'flex h-11 w-11 items-center justify-center rounded-xl bg-white/95 text-brand-dark shadow-[0_8px_24px_-8px_rgba(0,0,0,0.5)]'
            : 'flex h-11 w-11 items-center justify-center rounded-xl bg-[linear-gradient(135deg,#c53536_0%,#ea4d4e_100%)] text-white shadow-[0_8px_20px_-8px_rgba(197,53,54,0.7)]'
        }
      >
        <Workflow size={24} strokeWidth={2.2} />
      </span>
      <span className={dark ? 'text-xl font-semibold tracking-tight text-white' : 'text-xl font-semibold tracking-tight text-title'}>
        Operation Agents
      </span>
    </div>
  )
}

/** A floating "live activity" chip, to show the agents at work. */
function FloatingChip({ className, d, children }: { className: string; d: string; children: ReactNode }) {
  return (
    <div className={`auth-bob absolute hidden items-center gap-3 rounded-2xl border border-white/25 bg-white/15 px-4 py-3 shadow-[0_20px_40px_-16px_rgba(0,0,0,0.45)] backdrop-blur-md min-[1360px]:flex ${className}`} style={{ '--d': d } as CSSProperties}>
      {children}
    </div>
  )
}

/** The left half: what the product does, animated. Hidden on small screens. */
function BrandPanel() {
  return (
    <aside className="relative hidden text-white lg:flex lg:w-[48%] lg:max-w-[760px] lg:flex-col lg:justify-between lg:p-12 xl:p-16">
      <div className="auth-rise relative" style={delay(0)}>
        <Brand dark />
      </div>

      <div className="relative">
        <p className="auth-rise mb-4 inline-flex items-center gap-2 rounded-full border border-white/25 bg-white/10 px-3 py-1 text-xs font-medium text-white/90 backdrop-blur" style={delay(120)}>
          <span className="relative flex h-2 w-2">
            <span className="auth-ping absolute inline-flex h-full w-full rounded-full bg-emerald-300" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-300" />
          </span>
          <Sparkles size={13} /> AI agents are working right now
        </p>
        <h2 className="auth-rise max-w-md text-[34px] font-semibold leading-tight tracking-tight xl:text-[44px]" style={delay(220)}>
          Procurement that{' '}
          <span className="bg-[linear-gradient(90deg,#fff,#ffd0d1,#fff)] bg-clip-text text-transparent">runs itself.</span>
        </h2>
        <p className="auth-rise mt-3 max-w-md text-[15px] text-white/80" style={delay(320)}>
          From a one-line request to a delivered, matched order. You step in only when a decision is needed.
        </p>

        <ol className="relative mt-9 flex max-w-md flex-col">
          {/* the line the little light travels down */}
          <span className="absolute bottom-5 left-[19px] top-5 w-px bg-white/20" aria-hidden="true">
            <span className="auth-flow-dot absolute -left-[3px] h-2 w-2 rounded-full bg-white shadow-[0_0_12px_3px_rgba(255,255,255,0.8)]" />
          </span>
          {FLOW.map(({ Icon, title, text }, i) => (
            <li key={title} className="auth-rise relative flex gap-4 pb-5 last:pb-0" style={delay(420 + i * 110)}>
              <span
                className="auth-step relative flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-white/25 backdrop-blur"
                style={{ '--d': `${i * 2}s` } as CSSProperties}
              >
                <Icon size={19} />
              </span>
              <div className="pt-0.5">
                <p className="text-sm font-semibold">{title}</p>
                <p className="text-[13px] text-white/75">{text}</p>
              </div>
            </li>
          ))}
        </ol>
      </div>

      <p className="auth-rise relative flex items-center gap-2 text-xs text-white/70" style={delay(1100)}>
        <ShieldCheck size={14} /> Every action is audited and every user sees only what they're allowed to.
      </p>

      {/* floating live-status cards (wide screens only) */}
      <FloatingChip className="right-8 top-6" d="0s">
        <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-400/90 text-white"><CheckCircle2 size={18} /></span>
        <div>
          <p className="text-[13px] font-semibold">Quote received</p>
          <p className="text-xs text-white/75">Acme Supplies · 42,000</p>
        </div>
      </FloatingChip>
      <FloatingChip className="right-14 top-[104px]" d="1.5s">
        <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-white text-brand-dark"><FileText size={18} /></span>
        <div>
          <p className="text-[13px] font-semibold">PO-1042 issued</p>
          <p className="text-xs text-white/75">Sent to supplier automatically</p>
        </div>
      </FloatingChip>
    </aside>
  )
}

interface AuthLayoutProps {
  title: string
  subtitle: string
  onSubmit: (e: FormEvent) => void
  children: ReactNode
}

/** Split screen shared by sign-in and forgot-password: animated brand story on the left, the form on the right. */
export function AuthLayout({ title, subtitle, onSubmit, children }: AuthLayoutProps) {
  return (
    <div className="fixed inset-0 flex overflow-y-auto overflow-x-hidden bg-[radial-gradient(circle_at_20%_10%,#ea4d4e_0%,#a82b2c_48%,#3d0709_100%)]">
      {/* one background for the whole screen: drifting light over a faint dotted grid */}
      <div className="auth-blob-a pointer-events-none fixed -left-24 -top-24 h-[420px] w-[420px] rounded-full bg-white/15 blur-3xl" />
      <div className="auth-blob-b pointer-events-none fixed -bottom-32 -right-20 h-[460px] w-[460px] rounded-full bg-[#ff8a8b]/25 blur-3xl" />
      <div className="auth-blob-c pointer-events-none fixed left-1/3 top-1/2 h-[260px] w-[260px] rounded-full bg-[#ffb3b4]/15 blur-3xl" />
      <div className="auth-grid pointer-events-none fixed inset-0" />

      <BrandPanel />

      <main className="relative flex min-h-full flex-1 flex-col items-center justify-center px-5 py-8 sm:px-10">
        {/* Phones and tablets have no brand panel, so the logo sits above the form instead. */}
        <div className="auth-rise relative mb-8 lg:hidden" style={delay(0)}>
          <Brand dark />
        </div>

        {/* a still, thin white edge around the card (no moving glow) */}
        <div className="auth-pop relative w-full max-w-[440px] rounded-[28px] bg-white/60 p-[1.5px] shadow-[0_30px_70px_-20px_rgba(40,4,6,0.7)]" style={delay(150)}>
          <form onSubmit={onSubmit} noValidate className="auth-form flex flex-col gap-4 rounded-[26.5px] bg-white p-7 sm:gap-5 sm:p-10">
            <div className="flex flex-col items-center text-center">
              <span className="auth-badge mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-[linear-gradient(135deg,#c53536_0%,#ff6b6c_100%)] text-white">
                <Lock size={28} strokeWidth={2.2} />
              </span>
              <h1 className="bg-[linear-gradient(90deg,#222529,#b03a3b)] bg-clip-text text-2xl font-semibold leading-tight text-transparent sm:text-[30px]">{title}</h1>
              <p className="mt-1.5 text-sm text-muted">{subtitle}</p>
            </div>
            {children}
          </form>
        </div>
      </main>
    </div>
  )
}
