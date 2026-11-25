export interface ManagedUser {
  user_id: string
  username: string
  email: string | null
  display_name: string | null
  /** Full access, including managing users. Such a user holds every permission. */
  is_admin: boolean
  /** Everything this user may do (an admin holds all of them). */
  permissions: string[]
  is_active: boolean
  is_locked: boolean
  last_login_at: string | null
  created_at: string
  /** Leave (calendar days, India time) and the backup who is asked instead while away. */
  on_leave_from: string | null
  on_leave_until: string | null
  on_leave_now: boolean
  delegate_user_id: string | null
  delegate_name: string | null
}

/** One checkbox on the access form (Read only, CRUD, ...). Ticking it grants `permissions`. */
export interface AccessLevel {
  key: string
  label: string
  permissions: string[]
  /** Levels that must also be ticked: CRUD includes Read only. */
  implies: string[]
}

export interface PermissionGroup {
  resource: string
  label: string
  permissions: { key: string; label: string; description: string }[]
  levels: AccessLevel[]
}

/** One agent's human counterpart: the people asked when that agent is stuck. A quick way to tick the right boxes. */
export interface Department {
  key: string
  label: string
  agent: string
  handles: string
  permissions: string[]
}

export interface CreateUserRequest {
  email: string
  display_name?: string
  password: string
  is_admin: boolean
  permissions: string[]
}

export interface UpdateUserRequest {
  display_name?: string
  email?: string
  is_active?: boolean
  is_admin?: boolean
  /** The user's complete set of permissions. Leave out to keep it as it is. */
  permissions?: string[]
  /** Sent only when changed; null clears. */
  on_leave_from?: string | null
  on_leave_until?: string | null
  delegate_user_id?: string | null
}
