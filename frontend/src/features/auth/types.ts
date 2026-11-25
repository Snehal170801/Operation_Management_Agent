export interface AuthUser {
  user_id: string
  username: string
  email: string | null
  display_name: string | null
  role: string
  permissions: string[]
}

/** A short-lived sign-in for another account, opened by an administrator from the Accounts tab. */
export interface OpenedAccount extends AuthResponse {
  /** The administrator who opened it. */
  opened_by: string
}

export interface AuthResponse {
  access_token: string
  token_type: string
  expires_in: number
  user: AuthUser
}
