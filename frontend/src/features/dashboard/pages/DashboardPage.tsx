import { LiveDashboard } from '../LiveDashboard'

export function DashboardPage() {
  return (
    <div className="flex w-full flex-col">
      <h1 className="page-title pb-1">Dashboard</h1>
      <div className="pb-4" />
      <LiveDashboard />
    </div>
  )
}
