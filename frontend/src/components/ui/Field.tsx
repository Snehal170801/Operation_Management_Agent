import { useState, type InputHTMLAttributes, type TextareaHTMLAttributes } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import clsx from 'clsx'

const base =
  'w-full rounded-xl border border-line bg-white px-4 text-sm text-title placeholder:text-muted/70 focus:border-brand focus:outline-none focus:ring-4 focus:ring-brand/15'

export function Input({ label, className, ...rest }: InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  return (
    <label className="flex flex-col gap-1.5 text-xs font-medium text-muted">
      {label}
      <input {...rest} className={clsx(base, 'h-11', className)} />
    </label>
  )
}

/** Password field with a show/hide toggle. */
export function PasswordInput({ label, className, ...rest }: Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> & { label: string }) {
  const [visible, setVisible] = useState(false)
  return (
    <label className="flex flex-col gap-1.5 text-xs font-medium text-muted">
      {label}
      <span className="relative">
        <input {...rest} type={visible ? 'text' : 'password'} className={clsx(base, 'h-11 pr-11', className)} />
        <button
          type="button"
          onClick={() => setVisible((v) => !v)}
          aria-label={visible ? 'Hide password' : 'Show password'}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-muted hover:text-title"
        >
          {visible ? <EyeOff size={18} /> : <Eye size={18} />}
        </button>
      </span>
    </label>
  )
}

export function Textarea({ label, className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement> & { label: string }) {
  return (
    <label className="flex flex-col gap-1.5 text-xs font-medium text-muted">
      {label}
      <textarea {...rest} className={clsx(base, 'py-3', className)} />
    </label>
  )
}
