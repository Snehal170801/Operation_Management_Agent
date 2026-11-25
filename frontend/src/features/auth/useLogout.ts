import { useCallback } from 'react'
import { useConfirm } from '@/components/ui/confirm-context'
import { useAuth } from './AuthContext'

/** Asks "Log out?" first, then signs out. Used by every logout button so they all behave the same. */
export function useLogout(): () => Promise<void> {
  const { logout, openedBy } = useAuth()
  const confirm = useConfirm()

  return useCallback(async () => {
    const ok = await confirm(
      openedBy
        ? { title: 'Close this account?', message: 'This only closes this tab. Your own session is not affected.', confirmLabel: 'Close tab' }
        : { title: 'Log out?', message: "You'll need to sign in again to continue.", confirmLabel: 'Log out' },
    )
    if (ok) await logout()
  }, [confirm, logout, openedBy])
}
