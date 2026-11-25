import { useEffect, useState } from 'react'
import { Outlet } from 'react-router-dom'
import { useMedia } from '@/hooks/useMedia'
import { ConnectionBanner } from '@/features/live/ConnectionBanner'
import { useLiveUpdates } from '@/features/live/useLiveUpdates'
import { useAuth } from '@/features/auth/AuthContext'
import { useLogout } from '@/features/auth/useLogout'
import { ToastHost } from '@/features/notifications/ToastHost'
import { Navbar } from './Navbar'
import { Sidebar } from './Sidebar'

const COLLAPSED_KEY = 'operation-agents.sidebar.collapsed'

export function AppShell() {
  useLiveUpdates()
  const { user, openedBy } = useAuth()
  const closeAccount = useLogout()
  // Remembered across refreshes (per browser); if storage is blocked it simply starts expanded.
  const [collapsed, setCollapsedState] = useState(() => {
    try {
      return localStorage.getItem(COLLAPSED_KEY) === '1'
    } catch {
      return false
    }
  })
  const setCollapsed = (update: (current: boolean) => boolean) =>
    setCollapsedState((current) => {
      const next = update(current)
      try {
        localStorage.setItem(COLLAPSED_KEY, next ? '1' : '0')
      } catch {
        /* not remembered */
      }
      return next
    })
  // Below 1024px the menu is a slide-over drawer, closed until the menu button is pressed.
  const narrow = useMedia('(max-width: 1023px)')
  const [drawerRequested, setDrawerOpen] = useState(false)
  const drawerOpen = narrow && drawerRequested

  useEffect(() => {
    if (!drawerOpen) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setDrawerOpen(false)
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [drawerOpen])

  return (
    <div className="flex h-dvh w-full overflow-hidden bg-page">
      {!narrow && <Sidebar collapsed={collapsed} />}
      {narrow && drawerOpen && (
        <>
          <button
            type="button"
            aria-label="Close menu"
            onClick={() => setDrawerOpen(false)}
            className="fixed inset-0 z-30 bg-title/40"
          />
          <div className="fixed inset-y-0 left-0 z-40 shadow-xl">
            <Sidebar onNavigate={() => setDrawerOpen(false)} />
          </div>
        </>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        {openedBy && (
          <div role="status" className="flex shrink-0 flex-wrap items-center justify-center gap-x-4 gap-y-1 bg-amber-100 px-4 py-2 text-sm text-amber-950">
            <span>
              Viewing as <b>{user?.display_name || user?.username}</b>, opened by {openedBy}. What you do here is recorded under this account.
              Reloading ends it.
            </span>
            <button type="button" onClick={() => void closeAccount()} className="font-semibold underline hover:no-underline">
              Close this tab
            </button>
          </div>
        )}
        <ConnectionBanner />
        <Navbar onToggleSidebar={() => (narrow ? setDrawerOpen((o) => !o) : setCollapsed((c) => !c))} />
        <main className="min-h-0 flex-1 overflow-y-auto px-4 pb-4 pt-4 sm:px-6 sm:pb-5 sm:pt-5">
          <Outlet />
        </main>
      </div>
      <ToastHost />
    </div>
  )
}
