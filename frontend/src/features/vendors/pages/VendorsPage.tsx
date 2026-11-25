import { useMemo, useState, type FormEvent } from 'react'
import { Pencil, Plus, Star } from 'lucide-react'
import { CallButton } from '@/features/calls/CallButton'
import { Button } from '@/components/ui/Button'
import { useConfirm } from '@/components/ui/confirm-context'
import { useAuth } from '@/features/auth/AuthContext'
import { Card } from '@/components/ui/Card'
import { Input } from '@/components/ui/Field'
import { Modal } from '@/components/ui/Modal'
import { DEFAULT_PAGE_SIZE, Pagination } from '@/components/ui/Pagination'
import { QueryState } from '@/components/ui/QueryState'
import { Table, Td, Tr } from '@/components/ui/Table'
import { formatDateTime } from '@/lib/format'
import { EditVendorModal } from '../components/EditVendorModal'
import { useUpsertVendor, useVendors } from '../hooks'
import { LANGUAGES, toPhone } from '../phone'
import type { CallLanguage, Vendor } from '../types'

export function VendorsPage() {
  const { can } = useAuth()
  const { data, isLoading, error } = useVendors()
  const upsert = useUpsertVendor()
  const confirm = useConfirm()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [language, setLanguage] = useState<CallLanguage>('hi')
  const [score, setScore] = useState(3)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)
  const [editing, setEditing] = useState<Vendor | null>(null)

  const vendors = useMemo(() => data ?? [], [data])
  const rows = vendors.slice((page - 1) * pageSize, page * pageSize)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    const e164 = toPhone(phone)
    if (phone.trim() && !e164) return // the field shows why; nothing is sent
    const existing = vendors.some((v) => v.name.toLowerCase() === name.trim().toLowerCase())
    const ok = await confirm({
      title: existing ? 'Update this vendor?' : 'Add this vendor?',
      message: existing
        ? `"${name.trim()}" already exists; its details will be replaced with what you entered.`
        : `"${name.trim()}" will be added as a supplier with a reliability score of ${score}.`,
      confirmLabel: existing ? 'Update vendor' : 'Add vendor',
    })
    if (!ok) return
    upsert.mutate(
      { name, reliability_score: score, email: email.trim() || undefined, phone: e164 ?? undefined, call_language: language },
      {
        onSuccess: () => {
          setName('')
          setEmail('')
          setPhone('')
          setLanguage('hi')
          setScore(3)
          setOpen(false)
        },
      },
    )
  }

  return (
    <div className="flex w-full flex-col xl:h-full">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 pb-4">
        <h1 className="page-title">Vendors</h1>
        {can('vendors:write') && (
          <div className="flex flex-wrap items-start gap-3">
            <CallButton />
            <Button onClick={() => setOpen(true)}>
              <Plus size={18} /> Add / update vendor
            </Button>
          </div>
        )}
      </div>

      <Card className="flex-1" bodyClassName="flex min-h-0 flex-col p-0">
        <QueryState variant="table" columns={7} isLoading={isLoading} error={error} isEmpty={!vendors.length} emptyMessage="No vendors yet.">
          <Table headers={['Sr.No.', 'Name', 'Email', 'Phone', 'Reliability', 'Added', 'Action']}>
            {rows.map((v, i) => (
              <Tr key={v.vendor_id}>
                <Td first>{String((page - 1) * pageSize + i + 1).padStart(2, '0')}.</Td>
                <Td>{v.name}</Td>
                <Td>
                  {v.email ?? <span className="text-danger">Missing - cannot be emailed</span>}
                  {v.email && v.email_bounced_at && (
                    <span className="mt-0.5 block text-xs font-medium text-danger" title={v.email_bounce_reason ?? undefined}>
                      Emails to this address bounce. Save a correct address to try again.
                    </span>
                  )}
                </Td>
                <Td>
                  {v.phone ? (
                    <span>
                      {v.phone} <span className="text-xs text-muted">· {LANGUAGES.find((l) => l.value === v.call_language)?.label}</span>
                    </span>
                  ) : (
                    <span className="text-muted">Not set</span>
                  )}
                </Td>
                <Td>
                  <span className="inline-flex items-center gap-1 font-semibold text-brand-ink">
                    <Star size={14} fill="currentColor" /> {v.reliability_score.toFixed(1)}
                  </span>
                </Td>
                <Td>{formatDateTime(v.created_at)}</Td>
                <Td>
                  {can('vendors:write') && (
                    <Button variant="secondary" onClick={() => setEditing(v)} aria-label={`Edit ${v.name}`}>
                      <Pencil size={15} /> Edit
                    </Button>
                  )}
                </Td>
              </Tr>
            ))}
          </Table>
        </QueryState>
        <Pagination
          page={page}
          pageSize={pageSize}
          totalItems={vendors.length}
          onPageChange={setPage}
          onPageSizeChange={(n) => { setPageSize(n); setPage(1) }}
          itemLabel="vendors"
        />
      </Card>

      <EditVendorModal vendor={editing} onClose={() => setEditing(null)} />

      <Modal open={open} title="Add or update vendor" onClose={() => setOpen(false)}>
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <Input label="Vendor name" required value={name} onChange={(e) => setName(e.target.value)} />
          <Input
            label="Email (leave blank to keep the current one)"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <Input
            label="Phone (called after we email them; leave blank to keep the current one)"
            type="tel"
            inputMode="tel"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="e.g. 9325642310"
          />
          {phone.trim() && !toPhone(phone) && <p className="-mt-2 text-xs text-danger">That doesn't look like a phone number. Include all the digits.</p>}
          <label className="flex flex-col gap-1.5 text-xs font-medium text-muted">
            Language the call is spoken in
            <select
              value={language}
              onChange={(e) => setLanguage(e.target.value as CallLanguage)}
              className="h-11 rounded-xl border border-line bg-white px-3 text-sm text-title focus:border-brand focus:outline-none focus:ring-4 focus:ring-brand/15"
            >
              {LANGUAGES.map((l) => (
                <option key={l.value} value={l.value}>{l.label}</option>
              ))}
            </select>
          </label>
          <Input
            label="Reliability score (0–5)"
            type="number"
            min={0}
            max={5}
            step={0.1}
            required
            value={score}
            onChange={(e) => setScore(Number(e.target.value))}
          />
          {upsert.error && <p className="text-sm text-danger">{upsert.error.message}</p>}
          <div className="flex justify-end gap-3">
            <Button type="button" variant="secondary" onClick={() => setOpen(false)}>Cancel</Button>
            <Button type="submit" loading={upsert.isPending}>Save</Button>
          </div>
        </form>
      </Modal>
    </div>
  )
}
