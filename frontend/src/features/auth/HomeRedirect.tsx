import { Navigate } from 'react-router-dom'
import { useAuth } from './AuthContext'

/** "/" sends each kind of user to their own home: admins to the dashboard, each department to its own queue, requesters to their requests. */
export function HomeRedirect() {
  const { can } = useAuth()
  // A department person (they can see all cases but don't control the system) starts on their own queue.
  if (can('cases:read_all') && !can('system:write')) return <Navigate to="/my-work" replace />
  if (can('dashboard:read')) return <Navigate to="/dashboard" replace />
  if (can('cases:create') || can('cases:read')) return <Navigate to="/requests" replace />
  return <Navigate to="/settings" replace />
}
