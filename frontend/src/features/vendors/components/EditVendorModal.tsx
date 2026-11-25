import { useState, type FormEvent } from 'react'
import { Button } from '@/components/ui/Button'
import { useConfirm } from '@/components/ui/confirm-context'
import { Input } from '@/components/ui/Field'
import { Modal } from '@/components/ui/Modal'
import { useUpdateVendor } from '../hooks'
import { LANGUAGES, toPhone } from '../phone'
import type { CallLanguage, Vendor } from '../types'

/** Change any detail of one supplier, including its name. An empty e-mail or phone clears it. */
export function EditVendorModal({ vendor, onClose }: { vendor: Vendor | null; onClose: () => void }) {
  return (
    <Modal open={!!vendor} title="Edit supplier" onClose={onClose}>
      {vendor && <EditForm key={vendor.vendor_id} vendor={vendor} onClose={onClose} />}
    </Modal>
  )
}

function EditForm({ vendor, onClose }: { vendor: Vendor; onClose: () => void }) {
  const update = useUpdateVendor()
  const confirm = useConfirm()
  const [name, setName] = useState(vendor.name)
  const [email, setEmail] = useState(vendor.email ?? '')
  const [phone, setPhone] = useState(vendor.phone ?? '')
  const [language, setLanguage] = useState<CallLanguage>(vendor.call_language)
  const [score, setScore] = useState(vendor.reliability_score)

  const e164 = toPhone(phone)
  const badPhone = phone.trim() !== '' && !e164
  const scoreOk = Number.isFinite(score) && score >= 0 && score <= 5

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (badPhone || !scoreOk) return
    const ok = await confirm({
      title: 'Save these changes?',
      message: (
        <>
          The details of <b>{vendor.name}</b> will be updated.
          {name.trim() !== vendor.name && <> It will be renamed to <b>{name.trim()}</b>.</>}
          {email.trim() === '' && vendor.email && <> Its e-mail address will be removed, so it can no longer be asked for quotes.</>}
        </>
      ),
      confirmLabel: 'Save changes',
    })
    if (!ok) return
    update.mutate(
      { id: vendor.vendor_id, body: { name: name.trim(), email: email.trim() || null, phone: e164, call_language: language, reliability_score: score } },
      { onSuccess: onClose },
    )
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <Input label="Supplier name" required value={name} onChange={(e) => setName(e.target.value)} />
      <Input label="E-mail (empty removes it)" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
      <Input label="Phone (empty removes it)" type="tel" inputMode="tel" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="e.g. 9325642310" />
      {badPhone && <p className="-mt-2 text-xs text-danger">That doesn't look like a phone number. Include all the digits.</p>}
      <label className="flex flex-col gap-1.5 text-xs font-medium text-muted">
        Language the call is spoken in
        <select
          value={language}
          onChange={(e) => setLanguage(e.target.value as CallLanguage)}
          className="h-11 rounded-xl border border-line bg-white px-3 text-sm text-title focus:border-brand focus:outline-none focus:ring-4 focus:ring-brand/15"
        >
          {LANGUAGES.map((l) => (
            <option key={l.value} value={l.value}>
              {l.label}
            </option>
          ))}
        </select>
      </label>
      <Input label="Reliability score (0–5)" type="number" min={0} max={5} step={0.1} required value={score} onChange={(e) => setScore(Number(e.target.value))} />
      {vendor.email && vendor.email_bounced_at && email.trim().toLowerCase() === vendor.email.toLowerCase() && (
        <p className="text-xs text-danger">Emails to this address bounce. Enter a correct address to try again.</p>
      )}
      {update.error && <p className="text-sm text-danger">{update.error.message}</p>}
      <div className="flex justify-end gap-3">
        <Button type="button" variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" loading={update.isPending} disabled={badPhone || !scoreOk}>
          Save changes
        </Button>
      </div>
    </form>
  )
}
