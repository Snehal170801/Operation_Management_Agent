import { useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { AlertTriangle, Check, CheckCircle2, Eye, EyeOff, Loader2, LogIn, Lock, Mail } from 'lucide-react'
import { AuthLayout, authButtonCls, authErrorCls, authIconCls, authInputCls, authLinkCls, authNoticeCls } from './AuthLayout'
import { useAuth } from './AuthContext'

/** Only ever bounce back to a path inside this app (never an external URL). */
function safeDestination(from: unknown): string {
  return typeof from === 'string' && from.startsWith('/') && !from.startsWith('//') && !from.startsWith('/login')
    ? from
    : '/'
}

export function LoginPage() {
  const { status, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const state = location.state as { from?: string; notice?: string } | null
  const destination = safeDestination(state?.from)

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [rememberMe, setRememberMe] = useState(false)
  const [capsLockOn, setCapsLockOn] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const emailRef = useRef<HTMLInputElement>(null)
  const passwordRef = useRef<HTMLInputElement>(null)

  if (status === 'authenticated') return <Navigate to={destination} replace />

  const checkCapsLock = (e: KeyboardEvent<HTMLInputElement>) => setCapsLockOn(e.getModifierState('CapsLock'))

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (!email.trim() || !password) {
      setError('Enter your email or username, and your password.')
      ;(email.trim() ? passwordRef : emailRef).current?.focus()
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      await login(email.trim(), password, rememberMe)
      navigate(destination, { replace: true })
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      setError(
        /fetch|network/i.test(message)
          ? "Couldn't reach the server. Check that it's running and reachable."
          : message,
      )
      setPassword('')
      passwordRef.current?.focus() // ready to retype, instead of leaving focus on the button
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthLayout title="Welcome back" subtitle="Sign in to continue to Operation Agents." onSubmit={onSubmit}>
      {state?.notice && (
        <p role="status" className={authNoticeCls}>
          <CheckCircle2 size={16} className="shrink-0" /> {state.notice}
        </p>
      )}

      <div className="auth-field relative">
        <label htmlFor="login-email" className="sr-only">Email or username</label>
        <Mail size={19} className={authIconCls} />
        <input
          id="login-email"
          ref={emailRef}
          type="text"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          aria-invalid={!!error && !email.trim()}
          value={email}
          onChange={(e) => { setEmail(e.target.value); if (error) setError(null) }}
          className={authInputCls}
          autoFocus
          autoComplete="username"
          placeholder="Email or username"
        />
      </div>

      <div>
        <div className="auth-field relative">
          <label htmlFor="login-password" className="sr-only">Password</label>
          <Lock size={19} className={authIconCls} />
          <input
            id="login-password"
            ref={passwordRef}
            type={showPassword ? 'text' : 'password'}
            aria-invalid={!!error && !password}
            value={password}
            onChange={(e) => { setPassword(e.target.value); if (error) setError(null) }}
            onKeyUp={checkCapsLock}
            onKeyDown={checkCapsLock}
            className={authInputCls}
            autoComplete="current-password"
            placeholder="Password"
          />
          <button
            type="button"
            onClick={() => setShowPassword((v) => !v)}
            aria-label={showPassword ? 'Hide password' : 'Show password'}
            aria-pressed={showPassword}
            className="absolute right-1.5 top-1/2 flex h-10 w-10 -translate-y-1/2 items-center justify-center rounded-xl text-muted transition-colors hover:bg-slate-200/70 hover:text-title"
          >
            {showPassword ? <EyeOff size={19} /> : <Eye size={19} />}
          </button>
        </div>
        {capsLockOn && (
          <p className="mt-2 flex items-center gap-1.5 text-xs font-medium text-amber-600">
            <AlertTriangle size={12} /> Caps Lock is on
          </p>
        )}
      </div>

      <div className="-mt-1 flex items-center justify-between gap-3">
        <label className="flex w-fit cursor-pointer select-none items-center gap-2.5 text-sm text-muted">
          <span className="relative h-[18px] w-[18px] shrink-0">
            <input
              type="checkbox"
              checked={rememberMe}
              onChange={(e) => setRememberMe(e.target.checked)}
              className="peer h-[18px] w-[18px] cursor-pointer appearance-none rounded-[5px] border border-slate-300 bg-white transition-colors checked:border-brand checked:bg-brand focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-brand/20"
            />
            <Check size={13} strokeWidth={3.5} className="pointer-events-none absolute inset-0 m-auto text-white opacity-0 peer-checked:opacity-100" />
          </span>
          Remember me
        </label>
        <Link to="/forgot-password" className={authLinkCls}>
          Forgot password?
        </Link>
      </div>

      {error && (
        <p role="alert" aria-live="assertive" className={authErrorCls}>
          {error}
        </p>
      )}

      <button type="submit" disabled={submitting || !email.trim() || !password} className={authButtonCls}>
        {submitting ? (
          <Loader2 size={20} className="animate-spin" />
        ) : (
          <>
            Sign in <LogIn size={19} className="transition-transform group-hover:translate-x-1" />
          </>
        )}
      </button>
    </AuthLayout>
  )
}
