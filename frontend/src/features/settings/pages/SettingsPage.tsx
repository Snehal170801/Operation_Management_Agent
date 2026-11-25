import { useSearchParams } from 'react-router-dom'
import { Bot, HeartPulse, SlidersHorizontal,ShieldCheck, UserCircle, type LucideIcon } from 'lucide-react'
import clsx from 'clsx'
import { useAuth } from '@/features/auth/AuthContext'
import { AutomationSection } from '../components/AutomationSection'
import { ConfigureSection } from '../components/ConfigureSection'
import { ProfileSection } from '../components/ProfileSection'
import { SecuritySection } from '../components/SecuritySection'
import { SystemHealthSection } from '../components/SystemHealthSection'

interface Tab {
  id: string
  label: string
  Icon: LucideIcon
  permission?: string
  render: () => React.ReactNode
}

const TABS: Tab[] = [
  { id: 'profile', label: 'Profile', Icon: UserCircle, render: () => <ProfileSection /> },
  { id: 'security', label: 'Security', Icon: ShieldCheck, render: () => <SecuritySection /> },
  { id: 'automation', label: 'Automation', Icon: Bot, permission: 'system:read', render: () => <AutomationSection /> },
  { id: 'configure', label: 'Configure', Icon: SlidersHorizontal, permission: 'system:read', render: () => <ConfigureSection /> },
  { id: 'health', label: 'System Health', Icon: HeartPulse, permission: 'system:read', render: () => <SystemHealthSection /> },
]

export function SettingsPage() {
  const { can } = useAuth()
  const [params, setParams] = useSearchParams()

  const tabs = TABS.filter((t) => !t.permission || can(t.permission))
  // The active tab lives in the URL so it survives a reload and can be linked to.
  const active = tabs.find((t) => t.id === params.get('tab')) ?? tabs[0]

  return (
    <div className="flex w-full max-w-6xl flex-col">
      <h1 className="page-title pb-4">Settings</h1>

      <div role="tablist" className="mb-4 flex flex-wrap gap-2">
        {tabs.map(({ id, label, Icon }) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={active.id === id}
            onClick={() => setParams({ tab: id }, { replace: true })}
            className={clsx(
              'inline-flex h-10 items-center gap-2 rounded-xl px-4 text-sm font-medium transition-colors',
              active.id === id ? 'bg-brand-soft text-brand-ink' : 'bg-white text-muted hover:bg-brand-tint',
            )}
          >
            <Icon size={17} /> {label}
          </button>
        ))}
      </div>

      <div role="tabpanel">{active.render()}</div>
    </div>
  )
}
