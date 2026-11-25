import { useEffect, useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { ArrowLeft, Check, Circle, Eye, EyeOff, KeyRound, Loader2, Lock, Mail, ShieldCheck } from 'lucide-react'
import clsx from 'clsx'
import { api } from '@/lib/api-client'
import { passwordProblems } from '@/features/settings/passwordPolicy'
import { AuthLayout, authButtonCls, authErrorCls, authIconCls, authInputCls, authLinkCls, authNoticeCls } from './AuthLayout'
import { useAuth } from './AuthContext'

const RESEND_SECONDS = 60

const RULES: { label: string; test: (p: string) => boolean }[] = [
  { label: '8+ characters', test: (p) => p.length >= 8 },
  { label: 'Lowercase', test: (p) => /[a-z]/.test(p) },
  { label: 'Uppercase', test: (p) => /[A-Z]/.test(p) },
  { label: 'A number', test: (p) => /\d/.test(p) },
]

function GlassPassword({
  id, value, onChange, placeholder, autoComplete,
}: { id: string; value: string; onChange: (v: string) => void; placeholder: string; autoComplete: string }) {
  const [visible, setVisible] = useState(false)
  return (
    <div className="auth-field relative">
      <label htmlFor={id} className="sr-only">{placeholder}</label>
      <Lock size={19} className={authIconCls} />
      <input
        id={id}
        type={visible ? 'text' : 'password'}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={authInputCls}
        autoComplete={autoComplete}
        placeholder={placeholder}
      />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        aria-label={visible ? 'Hide password' : 'Show password'}
        aria-pressed={visible}
        className="absolute right-1.5 top-1/2 flex h-10 w-10 -translate-y-1/2 items-center justify-center rounded-xl text-muted transition-colors hover:bg-slate-200/70 hover:text-title"
      >
        {visible ? <EyeOff size={19} /> : <Eye size={19} />}
      </button>
    </div>
  )
}

export function ForgotPasswordPage() {
  const { status } = useAuth()
  const navigate = useNavigate()

  const [step, setStep] = useState<'request' | 'reset'>('request')
  const [email, setEmail] = useState('')
  const [otp, setOtp] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const [cooldown, setCooldown] = useState(0)

  useEffect(() => {
    if (cooldown <= 0) return
    const t = setTimeout(() => setCooldown((c) => c - 1), 1000)
    return () => clearTimeout(t)
  }, [cooldown])

  if (status === 'authenticated') return <Navigate to="/" replace />

  async function sendCode() {
    setSubmitting(true)
    setError(null)
    try {
      const res = await api.post<{ message: string }>('/auth/forgot-password', { identifier: email.trim() })
      setInfo(res.message)
      setStep('reset')
      setOtp('')
      setCooldown(RESEND_SECONDS)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not send the code.')
    } finally {
      setSubmitting(false)
    }
  }

  async function onRequest(e: FormEvent) {
    e.preventDefault()
    if (!email.trim()) return setError('Enter your email.')
    await sendCode()
  }

  const problems = passwordProblems(newPassword, email.trim())
  const mismatch = confirm.length > 0 && confirm !== newPassword
  const canReset = /^\d{6}$/.test(otp) && problems.length === 0 && confirm === newPassword

  async function onReset(e: FormEvent) {
    e.preventDefault()
    if (!canReset) return
    setSubmitting(true)
    setError(null)
    try {
      await api.post('/auth/forgot-password/confirm', {
        identifier: email.trim(),
        otp,
        new_password: newPassword,
      })
      navigate('/login', { replace: true, state: { notice: 'Password updated. Sign in with your new password.' } })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not reset your password.')
    } finally {
      setSubmitting(false)
    }
  }

  const backLink = (
    <Link to="/login" className={`${authLinkCls} flex items-center justify-center gap-1.5`}>
      <ArrowLeft size={15} /> Back to login
    </Link>
  )

  if (step === 'request') {
    return (
      <AuthLayout title="Forgot password?" subtitle="Enter your email and we'll send you a 6-digit code." onSubmit={onRequest}>
        <div className="auth-field relative">
          <label htmlFor="fp-email" className="sr-only">Email</label>
          <Mail size={19} className={authIconCls} />
          <input
            id="fp-email"
            type="email"
            inputMode="email"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={authInputCls}
            autoFocus
            autoComplete="username"
            placeholder="Email"
          />
        </div>

        {error && (
          <p role="alert" className={authErrorCls}>{error}</p>
        )}

        <button type="submit" disabled={submitting || !email.trim()} className={authButtonCls}>
          {submitting ? <Loader2 size={20} className="animate-spin" /> : <>Send code <KeyRound size={20} className="transition-transform group-hover:translate-x-1" /></>}
        </button>
        {backLink}
      </AuthLayout>
    )
  }

  return (
    <AuthLayout title="Reset password" subtitle="Enter the code we emailed you and choose a new password." onSubmit={onReset}>
      {info && (
        <p role="status" className={authNoticeCls}>{info}</p>
      )}

      <div className="auth-field relative">
        <label htmlFor="fp-otp" className="sr-only">6-digit code</label>
        <ShieldCheck size={19} className={authIconCls} />
        <input
          id="fp-otp"
          inputMode="numeric"
          autoComplete="one-time-code"
          // no maxLength: a pasted "123 456" must be cleaned first, then cut to 6 digits by the handler below
          value={otp}
          onChange={(e) => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))}
          className={clsx(authInputCls, 'pl-14 pr-14 text-center text-xl font-semibold tracking-[0.5em] indent-[0.5em] placeholder:text-[15px] placeholder:font-normal placeholder:tracking-normal')}
          autoFocus
          placeholder="6-digit code"
        />
      </div>

      <GlassPassword id="fp-new" value={newPassword} onChange={setNewPassword} placeholder="New password" autoComplete="new-password" />
      <ul className="-mt-2 grid grid-cols-2 gap-x-4 gap-y-1">
        {RULES.map((rule) => {
          const ok = rule.test(newPassword)
          return (
            <li key={rule.label} className={clsx('flex items-center gap-1.5 text-xs', ok ? 'text-[#16A34A]' : 'text-muted')}>
              {ok ? <Check size={13} /> : <Circle size={11} />} {rule.label}
            </li>
          )
        })}
      </ul>

      <div>
        <GlassPassword id="fp-confirm" value={confirm} onChange={setConfirm} placeholder="Confirm new password" autoComplete="new-password" />
        {mismatch && <p className="mt-2 text-xs font-medium text-danger">Passwords don't match.</p>}
      </div>

      {error && (
        <p role="alert" className={authErrorCls}>{error}</p>
      )}

      <button type="submit" disabled={submitting || !canReset} className={authButtonCls}>
        {submitting ? <Loader2 size={20} className="animate-spin" /> : 'Reset password'}
      </button>

      <div className="flex items-center justify-between">
        <button
          type="button"
          disabled={cooldown > 0 || submitting}
          onClick={() => void sendCode()}
          className={`${authLinkCls} disabled:cursor-not-allowed disabled:text-muted disabled:no-underline`}
        >
          {cooldown > 0 ? `Resend code in ${cooldown}s` : 'Resend code'}
        </button>
        <button type="button" onClick={() => { setStep('request'); setError(null) }} className={authLinkCls}>
          Use a different email
        </button>
      </div>
      {backLink}
    </AuthLayout>
  )
}
