import { useState, type FormEvent } from 'react'
import { Check, Circle } from 'lucide-react'
import clsx from 'clsx'
import { Button } from '@/components/ui/Button'
import { useConfirm } from '@/components/ui/confirm-context'
import { Card } from '@/components/ui/Card'
import { PasswordInput } from '@/components/ui/Field'
import { useAuth } from '@/features/auth/AuthContext'
import { passwordProblems } from '../passwordPolicy'

const RULES: { label: string; test: (p: string, u: string) => boolean }[] = [
  { label: 'At least 8 characters', test: (p) => p.length >= 8 },
  { label: 'A lowercase letter', test: (p) => /[a-z]/.test(p) },
  { label: 'An uppercase letter', test: (p) => /[A-Z]/.test(p) },
  { label: 'A number', test: (p) => /\d/.test(p) },
]

export function SecuritySection() {
  const { user, changePassword } = useAuth()
  const ask = useConfirm()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [saving, setSaving] = useState(false)
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const problems = passwordProblems(next, user?.username)
  const mismatch = confirm.length > 0 && confirm !== next
  const canSubmit = current && next && confirm && !mismatch && problems.length === 0

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    const ok = await ask({
      title: 'Change your password?',
      message: "You'll stay signed in here, but every other device will be signed out.",
      confirmLabel: 'Change password',
    })
    if (!ok) return
    setSaving(true)
    setError(null)
    setDone(false)
    try {
      await changePassword(current, next)
      setCurrent('')
      setNext('')
      setConfirm('')
      setDone(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not change your password.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card title="Change password">
      <form onSubmit={onSubmit} className="flex max-w-md flex-col gap-4">
        <PasswordInput label="Current password" required autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
        <PasswordInput label="New password" required autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
        <ul className="-mt-1 grid grid-cols-2 gap-x-4 gap-y-1">
          {RULES.map((rule) => {
            const ok = rule.test(next, user?.username ?? '')
            return (
              <li key={rule.label} className={clsx('flex items-center gap-1.5 text-xs', ok ? 'text-[#16A34A]' : 'text-muted')}>
                {ok ? <Check size={13} /> : <Circle size={11} />} {rule.label}
              </li>
            )
          })}
        </ul>
        <PasswordInput label="Confirm new password" required autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        {mismatch && <p className="-mt-2 text-xs text-danger">Passwords don't match.</p>}

        <p className="rounded-xl bg-brand-tint px-4 py-2.5 text-xs text-brand-ink">
          Changing your password signs you out of every other device.
        </p>
        {error && <p role="alert" className="text-sm text-danger">{error}</p>}
        {done && (
          <p role="status" className="flex items-center gap-1.5 text-sm font-medium text-[#16A34A]">
            <Check size={16} /> Password changed. Other devices were signed out.
          </p>
        )}
        <Button type="submit" loading={saving} disabled={!canSubmit} className="self-start">
          Update password
        </Button>
      </form>
    </Card>
  )
}
