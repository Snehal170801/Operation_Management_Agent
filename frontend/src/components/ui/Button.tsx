import type { ButtonHTMLAttributes } from 'react'
import clsx from 'clsx'
import { Loader2 } from 'lucide-react'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary'
  loading?: boolean
}

export function Button({ variant = 'primary', loading, disabled, className, children, ...rest }: ButtonProps) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={clsx(
        'inline-flex h-10 items-center justify-center gap-2 rounded-xl px-5 text-sm font-semibold transition-opacity disabled:cursor-not-allowed disabled:opacity-60',
        variant === 'primary'
          ? 'bg-[linear-gradient(135deg,#c53536_0%,#ea4d4e_100%)] text-white hover:opacity-90'
          : 'border border-line bg-white text-title hover:bg-brand-tint',
        className,
      )}
    >
      {loading && <Loader2 size={16} className="animate-spin" />}
      {children}
    </button>
  )
}
