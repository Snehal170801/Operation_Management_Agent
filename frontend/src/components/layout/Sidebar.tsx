import { useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import {
  BarChart3,
  Boxes,
  ChevronDown,
  ClipboardCheck,
  ClipboardList,
  FilePlus2,
  FileQuestion,
  FileText,
  FolderSearch,
  Receipt,
  Inbox,
  LayoutDashboard,
  LogOut,
  Network,
  ScrollText,
  Settings,
  Truck,
  Users,
  Warehouse,
  Workflow,
  type LucideIcon,
} from 'lucide-react'
import clsx from 'clsx'
import { AccountsNav } from '@/features/accounts/AccountsNav'
import { useAuth } from '@/features/auth/AuthContext'
import { useLogout } from '@/features/auth/useLogout'
import { MyWorkBadge } from '@/features/my-work/MyWorkBadge'

interface NavItem {
  to: string
  label: string
  Icon: LucideIcon
  /** Hidden entirely when the user's role lacks it (the API re-checks regardless). */
  permission?: string
  /** Hidden when the user DOES hold this one (keeps the requester and staff menus separate). */
  hideWith?: string
}

interface NavGroup {
  /** Section heading (also its id). A group without a label is always shown, never collapsible. */
  label?: string
  items: NavItem[]
}

// Related pages live together. A group disappears when none of its pages is visible to the user.
const NAV_GROUPS: NavGroup[] = [
  {
    // The one unlabelled group (rendered with the key 'top'): a second unlabelled group would clash with it.
    items: [
      { to: '/dashboard', label: 'Dashboard', Icon: LayoutDashboard, permission: 'dashboard:read' },
      { to: '/my-work', label: 'My work', Icon: Inbox, permission: 'cases:read_all' },
      { to: '/store-room', label: 'Store Room', Icon: Warehouse, permission: 'storeroom:read' },
    ],
  },
  {
    label: 'Operations',
    items: [
      { to: '/requests', label: 'My requests', Icon: FilePlus2, permission: 'cases:create', hideWith: 'cases:read_all' },
      { to: '/agent-flow', label: 'Agent Flow', Icon: Network, permission: 'cases:read' },
      { to: '/cases', label: 'Cases', Icon: ClipboardList, permission: 'cases:read_all' },
      { to: '/purchase-orders', label: 'Purchase orders', Icon: FileText, permission: 'cases:read_all' },
      { to: '/invoices', label: 'Invoices', Icon: Receipt, permission: 'cases:read_all' },
      { to: '/document-store', label: 'Document store', Icon: FolderSearch, permission: 'cases:read' },
      { to: '/documents', label: 'Unmatched documents', Icon: FileQuestion, permission: 'cases:read_all' },
      { to: '/approvals', label: 'Approvals', Icon: ClipboardCheck, permission: 'approvals:read' },
      { to: '/reports', label: 'Reports', Icon: BarChart3, permission: 'dashboard:read' },
    ],
  },
  {
    label: 'Inventory & Suppliers',
    items: [
      { to: '/stock', label: 'Stock', Icon: Boxes, permission: 'stock:read', hideWith: 'storeroom:read' },
      { to: '/vendors', label: 'Vendors', Icon: Truck, permission: 'vendors:read', hideWith: 'storeroom:read' },
    ],
  },
  {
    label: 'Administration',
    items: [
      { to: '/users', label: 'Users', Icon: Users, permission: 'users:read' },
      { to: '/audit', label: 'Audit Log', Icon: ScrollText, permission: 'audit:read' },
      // No permission: everyone has Settings (their own profile and password), so this group is never empty.
      { to: '/settings', label: 'Settings', Icon: Settings },
    ],
  },
]

// Which groups the user folded away is remembered per browser (a convenience, never relied on).
const CLOSED_KEY = 'operation-agents.sidebar.closed-groups'

function readClosed(): string[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(CLOSED_KEY) ?? '[]')
    return Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === 'string') : []
  } catch {
    return []
  }
}

function writeClosed(closed: string[]) {
  try {
    localStorage.setItem(CLOSED_KEY, JSON.stringify(closed))
  } catch {
    /* storage unavailable: the groups simply won't be remembered */
  }
}

const isOn = (pathname: string, to: string) => pathname === to || pathname.startsWith(`${to}/`)

interface SidebarProps {
  collapsed?: boolean
  onNavigate?: () => void
}

function NavItemLink({ item, collapsed, onNavigate }: { item: NavItem; collapsed: boolean; onNavigate?: () => void }) {
  const { to, label, Icon } = item
  return (
    <NavLink
      to={to}
      onClick={onNavigate}
      title={collapsed ? label : undefined}
      aria-label={label}
      className={({ isActive }) =>
        clsx(
          'relative mb-1 flex h-11 w-full items-center rounded-lg text-[14px] font-medium transition-colors duration-150',
          collapsed ? 'justify-center px-0' : 'gap-3 px-3',
          isActive ? 'bg-brand-soft text-brand-ink' : 'text-muted hover:bg-brand-tint',
        )
      }
    >
      <Icon size={20} strokeWidth={2.2} className="shrink-0" />
      {!collapsed && <span className="truncate">{label}</span>}
      {to === '/my-work' && <MyWorkBadge collapsed={collapsed} />}
    </NavLink>
  )
}

/** Full-height white rail: 260px expanded / 72px collapsed, collapsible sections, soft-pink active pill. */
export function Sidebar({ collapsed = false, onNavigate }: SidebarProps) {
  const { can } = useAuth()
  const logout = useLogout()
  const { pathname } = useLocation()
  const [closed, setClosed] = useState<string[]>(readClosed)
  const [seenPath, setSeenPath] = useState(pathname)

  const visible = (item: NavItem) => (!item.permission || can(item.permission)) && !(item.hideWith && can(item.hideWith))
  const groups = NAV_GROUPS.map((group) => ({ ...group, items: group.items.filter(visible) })).filter(
    (group) => group.items.length > 0,
  )

  // Navigating (a link, the back button, a deep link) opens the section that holds the page you land on.
  // Adjusting state during render is React's supported way to derive state from a changed input.
  if (seenPath !== pathname) {
    setSeenPath(pathname)
    const active = groups.find((g) => g.label && g.items.some((i) => isOn(pathname, i.to)))?.label
    if (active && closed.includes(active)) {
      const next = closed.filter((l) => l !== active)
      setClosed(next)
      writeClosed(next)
    }
  }

  function toggle(label: string) {
    const next = closed.includes(label) ? closed.filter((l) => l !== label) : [...closed, label]
    setClosed(next)
    writeClosed(next)
  }

  return (
    <aside
      className={clsx(
        'flex h-full shrink-0 flex-col border-r border-line bg-white transition-[width] duration-200 ease-in-out',
        collapsed ? 'w-[72px]' : 'w-[260px]',
      )}
    >
      <div className="flex h-16 shrink-0 items-center justify-center gap-2.5 overflow-hidden border-b border-line px-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[linear-gradient(135deg,#c53536_0%,#ea4d4e_100%)] text-white">
          <Workflow size={20} strokeWidth={2.2} />
        </span>
        {!collapsed && <span className="truncate text-[17px] font-semibold text-title">Operation Agents</span>}
      </div>

      <nav className="scrollbar-hide flex-1 overflow-y-auto px-3 pb-2 pt-3" aria-label="Main">
        {groups.map((group, index) => {
          const label = group.label
          // The icon-only rail has no room for headings or folding: show every item, groups split by a hairline.
          if (collapsed || !label) {
            return (
              <div key={label ?? 'top'} role="group" aria-label={label} className={clsx(index > 0 && 'mt-3')}>
                {collapsed && label && <div className="mx-2 mb-2 border-t border-line" />}
                {group.items.map((item) => (
                  <NavItemLink key={item.to} item={item} collapsed={collapsed} onNavigate={onNavigate} />
                ))}
              </div>
            )
          }

          const open = !closed.includes(label)
          const panelId = `sidebar-group-${label.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`
          const hasActive = group.items.some((i) => isOn(pathname, i.to))

          return (
            <div key={label} role="group" aria-label={label} className="mt-3">
              <button
                type="button"
                onClick={() => toggle(label)}
                aria-expanded={open}
                aria-controls={panelId}
                className="mb-1 flex h-8 w-full items-center justify-between rounded-lg px-3 text-[11px] font-semibold uppercase tracking-wider text-muted/80 transition-colors hover:bg-brand-tint hover:text-title"
              >
                <span className="flex items-center gap-2">
                  {label}
                  {/* Folded section that contains the page you're on: a dot says "you're in here". */}
                  {!open && hasActive && <span className="h-1.5 w-1.5 rounded-full bg-brand" aria-label="contains the current page" />}
                </span>
                <ChevronDown size={14} strokeWidth={2.4} className={clsx('transition-transform duration-200', !open && '-rotate-90')} />
              </button>

              {/* Animated fold: the 0fr -> 1fr grid row transition avoids measuring heights in JS. */}
              <div
                id={panelId}
                className={clsx('grid transition-[grid-template-rows] duration-200 ease-in-out', open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]')}
              >
                {/* `inert` keeps links in a folded section out of the tab order and away from screen readers. */}
                <div className="overflow-hidden" inert={!open}>
                  {group.items.map((item) => (
                    <NavItemLink key={item.to} item={item} collapsed={false} onNavigate={onNavigate} />
                  ))}
                </div>
              </div>
            </div>
          )
        })}
        {!collapsed && <AccountsNav closed={closed.includes('Accounts')} onToggle={() => toggle('Accounts')} />}
      </nav>

      <div className="shrink-0 border-t border-line px-3 py-3">
        <button
          type="button"
          onClick={() => void logout()}
          title={collapsed ? 'Log out' : undefined}
          aria-label="Log out"
          className={clsx(
            'flex h-11 w-full items-center rounded-lg text-[14px] font-medium text-danger transition-colors duration-150 hover:bg-danger-soft',
            collapsed ? 'justify-center px-0' : 'gap-3 px-3',
          )}
        >
          <LogOut size={20} strokeWidth={2.2} className="shrink-0" />
          {!collapsed && <span className="truncate">Log out</span>}
        </button>
      </div>
    </aside>
  )
}
