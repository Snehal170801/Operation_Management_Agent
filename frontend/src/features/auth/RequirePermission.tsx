import { Link, Outlet } from 'react-router-dom'
import { ShieldOff } from 'lucide-react'
import { useAuth } from './AuthContext'

/** Route guard: renders the child routes only if the user's role grants `permission`. */
export function RequirePermission({ permission }: { permission: string }) {
  const { can } = useAuth()
  if (can(permission)) return <Outlet />

  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
      <span className="flex h-14 w-14 items-center justify-center rounded-full bg-brand-soft text-brand-ink">
        <ShieldOff size={26} />
      </span>
      <h1 className="text-lg font-semibold text-title">You don't have access to this page</h1>
      <p className="max-w-sm text-sm text-muted">Ask an administrator if you need this permission.</p>
      <Link to="/" className="text-sm font-medium text-brand-ink hover:underline">
        Back to home
      </Link>
    </div>
  )
}
