import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { CheckCircle2, Phone, PhoneOff, XCircle } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Field'
import { Modal } from '@/components/ui/Modal'
import { api } from '@/lib/api-client'

interface CallStatus {
  configured: boolean
  /** Numbers the server will ring (CALL_ALLOWED_NUMBERS). Empty means any number is allowed. */
  allowed_numbers: string[]
}

/** Seconds to wait, once a complete number is in the box, before it dials by itself. */
const AUTO_DIAL_SECONDS = 3

/** "+919325642310" -> "+91 93256 42310" for display only. */
const pretty = (n: string) => n.replace(/^(\+91)(\d{5})(\d{5})$/, '$1 $2 $3')

/**
 * Turns how people write numbers into the +country-code form the server needs:
 * "09325642310", "9325642310", "93256 42310", "+91 93256-42310", "919325642310" -> "+919325642310".
 * Returns null if it doesn't look like a phone number.
 */
export function toE164(input: string): string | null {
  const raw = input.trim()
  const digits = raw.replace(/\D/g, '')
  if (raw.startsWith('+')) return digits.length >= 8 && digits.length <= 15 ? `+${digits}` : null
  if (digits.length === 10) return `+91${digits}`
  if (digits.length === 11 && digits.startsWith('0')) return `+91${digits.slice(1)}`
  if (digits.length === 12 && digits.startsWith('91')) return `+${digits}`
  return null
}

/** Only complete Indian numbers dial by themselves: for others there's no way to know when typing has finished. */
const isCompleteIndian = (n: string | null): n is string => !!n && /^\+91[6-9]\d{9}$/.test(n)

/** "Call" button: opens a box to type whom to call. A complete number dials itself after a short countdown. */
export function CallButton() {
  const status = useQuery({ queryKey: ['calls', 'status'], queryFn: () => api.get<CallStatus>('/calls/status'), staleTime: 30_000 })
  const [open, setOpen] = useState(false)
  if (!status.data) return null

  const ready = status.data.configured
  return (
    <>
      <Button
        variant="secondary"
        onClick={() => setOpen(true)}
        disabled={!ready}
        title={ready ? undefined : 'Calling is not set up yet (see the Exotel settings in the backend .env)'}
      >
        <Phone size={17} /> {ready ? 'Call' : 'Call (not set up)'}
      </Button>
      {open && <CallDialog onClose={() => setOpen(false)} />}
    </>
  )
}

function CallDialog({ onClose }: { onClose: () => void }) {
  const [typed, setTyped] = useState('')
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null)
  // Seconds left before it dials by itself; null = nothing pending.
  const [countdown, setCountdown] = useState<number | null>(null)
  const timer = useRef<ReturnType<typeof setInterval> | undefined>(undefined)
  const dialled = useRef<string | null>(null) // never auto-dial the same number twice in a row
  // The call that is ringing / connected right now, so it can be ended.
  const [active, setActive] = useState<{ sid: string; to: string } | null>(null)

  const call = useMutation({
    mutationFn: (to: string) => api.post<{ call_sid: string; to: string }>('/calls', { to }),
    onSuccess: (r) => {
      setActive({ sid: r.call_sid, to: r.to })
      setResult({ ok: true, text: `Calling ${pretty(r.to)}...` })
    },
    onError: (e: Error) => setResult({ ok: false, text: e.message }),
  })

  const end = useMutation({
    mutationFn: (sid: string) => api.post<void>(`/calls/${sid}/end`),
    onSuccess: () => {
      setActive(null)
      setResult({ ok: true, text: 'Call ended.' })
    },
    onError: (e: Error) => setResult({ ok: false, text: e.message }),
  })

  const stop = () => {
    clearInterval(timer.current)
    setCountdown(null)
  }
  useEffect(() => () => clearInterval(timer.current), [])

  function dial(to: string) {
    stop()
    dialled.current = to
    setResult(null)
    setActive(null)
    call.mutate(to)
  }

  function onChange(value: string) {
    setTyped(value)
    setResult(null)
    stop() // any edit cancels a pending call, so a typo never rings anyone

    const next = toE164(value)
    if (!isCompleteIndian(next) || next === dialled.current) return
    let left = AUTO_DIAL_SECONDS
    setCountdown(left)
    timer.current = setInterval(() => {
      left -= 1
      if (left <= 0) dial(next)
      else setCountdown(left)
    }, 1000)
  }

  const number = toE164(typed)

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (number) dial(number)
  }

  return (
    <Modal open title="Call a number" onClose={onClose}>
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <Input
          label="Phone number"
          type="tel"
          inputMode="tel"
          autoFocus
          required
          value={typed}
          onChange={(e) => onChange(e.target.value)}
          placeholder="e.g. 9325642310"
        />

        {countdown !== null && number && (
          <p role="status" className="flex items-center justify-between gap-3 rounded-xl bg-brand-tint px-4 py-2.5 text-sm text-brand-ink">
            <span>
              Calling <b>{pretty(number)}</b> in {countdown}…
            </span>
            <button type="button" onClick={stop} className="font-semibold underline underline-offset-2">
              Cancel
            </button>
          </p>
        )}

        {result && (
          <p role={result.ok ? 'status' : 'alert'} className={`flex items-start gap-1.5 text-sm ${result.ok ? 'text-[#16A34A]' : 'text-danger'}`}>
            {result.ok ? <CheckCircle2 size={16} className="mt-0.5 shrink-0" /> : <XCircle size={16} className="mt-0.5 shrink-0" />}
            <span>{result.text}</span>
          </p>
        )}

        {active && (
          <Button
            type="button"
            variant="secondary"
            className="border-danger/40 text-danger hover:bg-danger-soft"
            loading={end.isPending}
            onClick={() => end.mutate(active.sid)}
          >
            <PhoneOff size={16} /> End call
          </Button>
        )}

        <Button type="submit" loading={call.isPending} disabled={!number}>
          <Phone size={16} /> {active ? 'Call again' : 'Call now'}
        </Button>
      </form>
    </Modal>
  )
}
