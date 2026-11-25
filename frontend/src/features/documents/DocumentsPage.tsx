import { useState, type FormEvent } from 'react'
import { FileSearch, Paperclip } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { useConfirm } from '@/components/ui/confirm-context'
import { Modal } from '@/components/ui/Modal'
import { QueryState } from '@/components/ui/QueryState'
import { Table, Td, Tr } from '@/components/ui/Table'
import { useAuth } from '@/features/auth/AuthContext'
import { useCases } from '@/features/cases/hooks'
import { formatDateTime } from '@/lib/format'
import { useAttachDocument, useDismissDocument, useUnmatchedDocuments } from './hooks'
import type { UnmatchedDocument } from './types'

/** Documents a known supplier sent that name no order we could find (no case tag, no PO number we know). A person says which case they belong to. */
export function DocumentsPage() {
  const { can } = useAuth()
  const { data, isLoading, error } = useUnmatchedDocuments()
  const dismiss = useDismissDocument()
  const confirm = useConfirm()
  const [attaching, setAttaching] = useState<UnmatchedDocument | null>(null)
  const canHandle = can('invoices:decide') || can('vendors:write')
  const items = data ?? []

  async function onDismiss(doc: UnmatchedDocument) {
    const ok = await confirm({
      title: 'Dismiss this document?',
      message: `“${doc.subject || 'No subject'}” from ${doc.vendor_name ?? doc.from_email} will be removed from the list. Do this only if it needs no action (for example a duplicate).`,
      confirmLabel: 'Dismiss',
    })
    if (ok) dismiss.mutate({ id: doc.document_id })
  }

  return (
    <div className="flex w-full flex-col xl:h-full">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 pb-4">
        <div>
          <h1 className="page-title">Unmatched documents</h1>
          <p className="mt-1 text-sm text-muted">
            Supplier emails and PDFs that did not say which order they belong to. Attach each one to its case, and the agents carry on from there.
          </p>
        </div>
      </div>

      <Card className="flex-1" bodyClassName="flex min-h-0 flex-col p-0">
        <QueryState
          variant="table"
          columns={6}
          isLoading={isLoading}
          error={error ?? dismiss.error}
          isEmpty={!items.length}
          emptyMessage="Nothing is waiting. Every supplier document has found its order."
        >
          <Table headers={['Received', 'From', 'Subject', 'Files', 'What it says', 'Action']}>
            {items.map((d) => (
              <Tr key={d.document_id}>
                <Td first className="whitespace-nowrap">{formatDateTime(d.created_at)}</Td>
                <Td>
                  <span className="font-semibold">{d.vendor_name ?? d.from_email}</span>
                  {d.vendor_name && <span className="block text-xs text-muted">{d.from_email}</span>}
                </Td>
                <Td>{d.subject || <span className="text-muted">(no subject)</span>}</Td>
                <Td>
                  {d.file_names.length ? (
                    <span className="inline-flex items-center gap-1 text-sm">
                      <Paperclip size={14} /> {d.file_names.join(', ')}
                    </span>
                  ) : (
                    <span className="text-muted">None</span>
                  )}
                </Td>
                <Td className="max-w-[320px] text-sm text-muted">{d.summary || '–'}</Td>
                <Td>
                  {canHandle ? (
                    <div className="flex flex-wrap gap-2">
                      <Button onClick={() => setAttaching(d)}>
                        <FileSearch size={15} /> Attach to case
                      </Button>
                      <Button variant="secondary" onClick={() => void onDismiss(d)}>
                        Dismiss
                      </Button>
                    </div>
                  ) : (
                    <span className="text-sm text-muted">Accounts or the Vendor team will deal with it</span>
                  )}
                </Td>
              </Tr>
            ))}
          </Table>
        </QueryState>
      </Card>

      <AttachModal doc={attaching} onClose={() => setAttaching(null)} />
    </div>
  )
}

function AttachModal({ doc, onClose }: { doc: UnmatchedDocument | null; onClose: () => void }) {
  return (
    <Modal open={!!doc} title="Attach to a case" onClose={onClose}>
      {doc && <AttachForm key={doc.document_id} doc={doc} onClose={onClose} />}
    </Modal>
  )
}

function AttachForm({ doc, onClose }: { doc: UnmatchedDocument; onClose: () => void }) {
  const cases = useCases()
  const attach = useAttachDocument()
  const [caseId, setCaseId] = useState('')
  const open = (cases.data ?? []).filter((c) => c.status === 'open')

  function submit(event: FormEvent) {
    event.preventDefault()
    attach.mutate({ id: doc.document_id, caseId }, { onSuccess: onClose })
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <p className="text-sm text-muted">
        <b className="text-title">{doc.subject || 'No subject'}</b> from {doc.vendor_name ?? doc.from_email}
        {doc.file_names.length > 0 && <> ({doc.file_names.join(', ')})</>}. Choose the case it belongs to. It is then read and handled exactly as if the
        supplier had replied to that order.
      </p>
      <label className="flex flex-col gap-1.5 text-xs font-medium text-muted">
        Case
        <select
          required
          value={caseId}
          onChange={(e) => setCaseId(e.target.value)}
          className="h-11 rounded-xl border border-line bg-white px-3 text-sm text-title focus:border-brand focus:outline-none focus:ring-4 focus:ring-brand/15"
        >
          <option value="">Choose a case…</option>
          {open.map((c) => (
            <option key={c.case_id} value={c.case_id}>
              {c.case_number ?? c.case_id.slice(0, 8)} · {c.items_summary ?? 'request'} · {c.stage.replace(/_/g, ' ')}
            </option>
          ))}
        </select>
      </label>
      {cases.isLoading && <p className="text-xs text-muted">Loading cases…</p>}
      {attach.error && <p className="text-sm text-danger">{attach.error.message}</p>}
      <div className="flex justify-end gap-3">
        <Button type="button" variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" loading={attach.isPending} disabled={!caseId}>
          Attach and read it
        </Button>
      </div>
    </form>
  )
}
