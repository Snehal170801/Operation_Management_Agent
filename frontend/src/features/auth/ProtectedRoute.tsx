import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { AppShellSkeleton } from '@/components/ui/Skeleton'
import { useAuth } from './AuthContext'

export function ProtectedRoute() {
  const { status } = useAuth()
  const location = useLocation()

  if (status === 'loading') return <AppShellSkeleton />
  if (status === 'anonymous') {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  }
  return <Outlet />
}
