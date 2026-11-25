import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { AlertTriangle, HelpCircle } from 'lucide-react'
import clsx from 'clsx'
import { ConfirmContext, type ConfirmFn, type ConfirmOptions } from './confirm-context'

interface Pending {
  options: ConfirmOptions
  resolve: (confirmed: boolean) => void
}

/** Renders the one shared confirmation dialog, above any other modal that is open. */
export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<Pending | null>(null)
  const cancelRef = useRef<HTMLButtonElement>(null)
  const confirmRef = useRef<HTMLButtonElement>(null)

  const confirm = useCallback<ConfirmFn>(
    (options) =>
      new Promise<boolean>((resolve) => {
        // A second request while one is open cancels the first, so no promise is ever left hanging.
        setPending((current) => {
          current?.resolve(false)
          return { options, resolve }
        })
      }),
    [],
  )

  const answer = useCallback(
    (value: boolean) => {
      pending?.resolve(value)
      setPending(null)
    },
    [pending],
  )

  const danger = pending?.options.tone === 'danger'

  useEffect(() => {
    if (!pending) return
    // Safe default: destructive prompts focus Cancel, so a stray Enter can't delete something.
    ;(danger ? cancelRef : confirmRef).current?.focus()

    // Capture on window so Escape closes only this dialog, not the form modal underneath it.
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopImmediatePropagation()
        answer(false)
      }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [pending, danger, answer])

  const Icon = danger ? AlertTriangle : HelpCircle

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {pending && (
        <div
          className="fixed inset-0 z-[80] flex items-center justify-center bg-black/50 p-4"
          onClick={() => answer(false)}
        >
          <div
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="confirm-title"
            aria-describedby={pending.options.message ? 'confirm-message' : undefined}
            className="flex w-full max-w-[420px] flex-col gap-5 rounded-2xl border border-line bg-white p-6 shadow-[0_8px_40px_rgba(0,0,0,0.22)]"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start gap-4">
              <span
                className={clsx(
                  'flex h-11 w-11 shrink-0 items-center justify-center rounded-full',
                  danger ? 'bg-danger-soft text-danger' : 'bg-brand-soft text-brand-ink',
                )}
              >
                <Icon size={22} />
              </span>
              <div className="min-w-0">
                <h3 id="confirm-title" className="text-[17px] font-semibold text-title">
                  {pending.options.title}
                </h3>
                {pending.options.message && (
                  <div id="confirm-message" className="mt-1.5 text-sm text-muted">
                    {pending.options.message}
                  </div>
                )}
              </div>
            </div>

            <div className="flex justify-end gap-3">
              <button
                ref={cancelRef}
                type="button"
                onClick={() => answer(false)}
                className="inline-flex h-10 items-center rounded-xl border border-line bg-white px-5 text-sm font-semibold text-title hover:bg-brand-tint focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-brand/20"
              >
                {pending.options.cancelLabel ?? 'Cancel'}
              </button>
              <button
                ref={confirmRef}
                type="button"
                onClick={() => answer(true)}
                className={clsx(
                  'inline-flex h-10 items-center rounded-xl px-5 text-sm font-semibold text-white hover:opacity-90 focus-visible:outline-none focus-visible:ring-4',
                  danger
                    ? 'bg-danger focus-visible:ring-danger/25'
                    : 'bg-[linear-gradient(135deg,#c53536_0%,#ea4d4e_100%)] focus-visible:ring-brand/25',
                )}
              >
                {pending.options.confirmLabel ?? 'Confirm'}
              </button>
            </div>
          </div>
        </div>
      )}
    </ConfirmContext.Provider>
  )
}
