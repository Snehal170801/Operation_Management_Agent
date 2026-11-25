import { useEffect, type ReactNode } from 'react'
import { X } from 'lucide-react'
import clsx from 'clsx'

interface ModalProps {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
  /** `lg` for forms with a table in them (e.g. the access checkmarks). */
  size?: 'md' | 'lg'
}

export function Modal({ open, title, onClose, children, size = 'md' }: ModalProps) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/45 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-label={title}
        className={clsx(
          'flex max-h-[92dvh] w-full flex-col gap-5 overflow-y-auto rounded-2xl border border-line bg-white p-6 shadow-[0_8px_40px_rgba(0,0,0,0.18)]',
          size === 'lg' ? 'max-w-[680px]' : 'max-w-[480px]',
        )}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h3 className="text-[17px] font-semibold text-title">{title}</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex h-9 w-9 items-center justify-center rounded-full bg-brand-tint text-brand-ink hover:bg-brand-soft"
          >
            <X size={18} />
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}
