import { useState } from 'react'
import { CheckCircle2, PackageCheck, PackageX } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { NoteModal } from '@/components/ui/NoteModal'
import { useAnswerReceipt, useMyReceipt } from '@/features/delivery/receipt'
import { formatDateTime } from '@/lib/format'

/** After Receiving marks the goods received, the person who asked is asked: did they actually reach you? */
export function ReceiptCard({ caseId }: { caseId: string }) {
  const receipt = useMyReceipt(caseId)
  const answer = useAnswerReceipt(caseId)
  const [reporting, setReporting] = useState(false)
  const r = receipt.data

  // Nothing to ask yet (or still loading): show nothing rather than an empty box.
  if (!r || r.state === 'not_delivered') return null

  const asking = r.state === 'ask' || r.state === 'followed_up'

  return (
    <Card title="Did the goods reach you?">
      <div className="flex flex-col gap-4 text-sm">
        {r.state === 'confirmed' && (
          <p className="flex items-start gap-2 text-[#16A34A]">
            <CheckCircle2 size={18} className="mt-0.5 shrink-0" />
            <span>Thank you. You confirmed you received it{r.at ? ` on ${formatDateTime(r.at)}` : ''}.</span>
          </p>
        )}
        {r.state === 'disputed' && (
          <p className="flex items-start gap-2 text-danger">
            <PackageX size={18} className="mt-0.5 shrink-0" />
            <span>
              You told us it has not reached you{r.note ? `: “${r.note}”` : ''}. The Receiving team has been told and will get in touch.
            </span>
          </p>
        )}
        {r.state === 'followed_up' && (
          <p className="rounded-xl bg-brand-tint px-4 py-3 text-title">The Receiving team has looked into it. Has the order reached you now?</p>
        )}
        {r.state === 'ask' && <p className="text-muted">The store says this order has arrived. Please tell us if it reached you.</p>}

        {asking && (
          <div className="flex flex-wrap gap-3">
            <Button loading={answer.isPending && answer.variables?.received === true} onClick={() => answer.mutate({ received: true })}>
              <PackageCheck size={16} /> Yes, I got it
            </Button>
            <Button variant="secondary" onClick={() => setReporting(true)}>
              <PackageX size={16} /> No, not received
            </Button>
          </div>
        )}
        {r.state === 'confirmed' && (
          <button type="button" onClick={() => setReporting(true)} className="w-fit text-xs text-muted underline hover:text-title">
            Something is wrong after all
          </button>
        )}
        {answer.error && !reporting && <p className="text-danger">{answer.error.message}</p>}

        <NoteModal
          open={reporting}
          title="Tell Receiving what is wrong"
          description="For example: nothing arrived, only part of it, or the wrong item. The Receiving team is alerted straight away."
          confirmLabel="Send to Receiving"
          danger
          loading={answer.isPending}
          error={answer.error}
          onClose={() => {
            setReporting(false)
            answer.reset()
          }}
          onConfirm={(note) => answer.mutate({ received: false, note }, { onSuccess: () => setReporting(false) })}
        />
      </div>
    </Card>
  )
}
