import { useEffect, useRef, useState } from 'react'
import { LogOut, Menu } from 'lucide-react'
import { useAuth } from '@/features/auth/AuthContext'
import { useLogout } from '@/features/auth/useLogout'
import { NotificationBell } from '@/features/notifications/NotificationBell'
import { humanize } from '@/lib/format'

/** Slim white top bar: hamburger on the left, notifications + account menu on the right. */
export function Navbar({ onToggleSidebar }: { onToggleSidebar: () => void }) {
  const { user } = useAuth()
  const logout = useLogout()

  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!menuOpen) return
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false)
    }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setMenuOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [menuOpen])

  const name = user?.display_name || user?.username || 'Account'

  return (
    <header className="relative flex h-16 shrink-0 items-center justify-between gap-3 border-b border-line bg-white px-3 sm:px-6">
      <button
        type="button"
        onClick={onToggleSidebar}
        aria-label="Toggle sidebar"
        title="Toggle sidebar"
        className="flex h-10 w-10 items-center justify-center rounded-lg text-brand-ink transition-colors hover:bg-brand-tint"
      >
        <Menu className="h-[22px] w-[22px]" strokeWidth={2.4} />
      </button>

      <div className="flex items-center gap-4">
        <NotificationBell />

        <div className="relative" ref={menuRef}>
          <button
            type="button"
            onClick={() => setMenuOpen((o) => !o)}
            aria-label="Account menu"
            aria-expanded={menuOpen}
            className="flex items-center gap-3 text-left"
          >
            <span className="flex h-10 w-10 items-center justify-center rounded-full bg-brand-soft text-[15px] font-semibold text-brand-ink">
              {name.charAt(0).toUpperCase()}
            </span>
            <span className="hidden sm:block">
              <span className="block text-[14px] font-semibold leading-tight text-title">{name}</span>
              <span className="block text-[12px] leading-tight text-muted">{humanize(user?.role)}</span>
            </span>
          </button>

          {menuOpen && (
            <div className="absolute right-0 top-[calc(100%+8px)] z-50 w-[200px] rounded-xl border border-line bg-white py-2 shadow-lg">
              <button
                type="button"
                onClick={() => {
                  setMenuOpen(false)
                  void logout()
                }}
                className="flex w-full items-center gap-2.5 px-4 py-2.5 text-left text-sm font-medium text-danger transition-colors hover:bg-danger-soft"
              >
                <LogOut size={16} /> Log out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
