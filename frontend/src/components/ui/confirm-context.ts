import { createContext, useContext, type ReactNode } from 'react'

export interface ConfirmOptions {
  title: string
  message?: ReactNode
  /** Button text; name the action ("Delete role", "Save changes"), not just "OK". */
  confirmLabel?: string
  cancelLabel?: string
  /** `danger` for destructive or hard-to-undo actions: red button, and Cancel gets the initial focus. */
  tone?: 'default' | 'danger'
}

export type ConfirmFn = (options: ConfirmOptions) => Promise<boolean>

export const ConfirmContext = createContext<ConfirmFn | null>(null)

/**
 * Ask the user to confirm before a create / update / delete:
 *
 *   const confirm = useConfirm()
 *   if (!(await confirm({ title: 'Delete role?', tone: 'danger', confirmLabel: 'Delete' }))) return
 */
export function useConfirm(): ConfirmFn {
  const confirm = useContext(ConfirmContext)
  if (!confirm) throw new Error('useConfirm must be used inside <ConfirmProvider>')
  return confirm
}
